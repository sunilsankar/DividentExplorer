"""End-to-end integration tests for Dividend Explorer."""

import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.backup import backup_database, restore_database
from app.db.models import (
    Base,
    Company,
    DividendEvent,
    DividendMetric,
    Exchange,
    FinancialMetric,
    PriceHistory,
    SyncJob,
    WorkerStatus,
)
from app.db.repositories import (
    CompanyRepository,
    DividendRepository,
    ExchangeRepository,
    FinancialRepository,
    PriceRepository,
)
from app.db.session import get_db
from app.main import app
from app.sync.handlers import dispatch_job
from app.sync.queue import SyncQueue, SyncRunManager, WorkerHeartbeatManager
from app.sync.rate_limiter import RateLimiter
from app.sync.worker import SyncWorker
from app.yahoo.client import (
    CompanyProfileData,
    DividendEventData,
    FinancialData,
    PriceHistoryData,
    YahooClient,
)
from unittest.mock import MagicMock


class EndToEndIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_integration.db")
        self.engine = create_engine(f"sqlite:///{self.db_path}")

        # Enforce WAL mode
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
            conn.exec_driver_sql("PRAGMA foreign_keys=ON;")

        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

        # Seed NYSE exchange
        with self.SessionLocal() as session:
            ex = Exchange(code="NYSE", name="New York Stock Exchange", country="USA", currency="USD")
            session.add(ex)
            session.commit()

        def override_get_db():
            s = self.SessionLocal()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.engine.dispose()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_pipeline_sync_api_ui_and_backup(self):
        """Test full pipeline: enqueue -> worker process -> API -> UI -> backup/restore."""
        # 1. Enqueue AAPL sync job
        with self.SessionLocal() as session:
            queue = SyncQueue()
            job = queue.enqueue(session, job_type="SYNC_COMPANY", ticker="AAPL", priority=1)
            session.commit()
            self.assertEqual(job.status, "PENDING")

        # 2. Mock Yahoo client data
        mock_profile = CompanyProfileData(
            ticker="AAPL",
            name="Apple Inc.",
            exchange_code="NYSE",
            sector="Technology",
            industry="Consumer Electronics",
            country="United States",
            currency="USD",
        )
        mock_dividends = [
            DividendEventData(ex_date=date(2023, 2, 10), pay_date=date(2023, 2, 16), amount=0.23),
            DividendEventData(ex_date=date(2023, 5, 12), pay_date=date(2023, 5, 18), amount=0.24),
            DividendEventData(ex_date=date(2023, 8, 11), pay_date=date(2023, 8, 17), amount=0.24),
            DividendEventData(ex_date=date(2023, 11, 10), pay_date=date(2023, 11, 16), amount=0.24),
            DividendEventData(ex_date=date(2024, 2, 9), pay_date=date(2024, 2, 15), amount=0.24),
            DividendEventData(ex_date=date(2024, 5, 10), pay_date=date(2024, 5, 16), amount=0.25),
        ]
        mock_prices = [
            PriceHistoryData(date=date(2024, 5, 16), open=188.0, high=190.0, low=187.5, close=189.84, adj_close=189.84, volume=50000000)
        ]
        mock_financials = FinancialData(
            market_cap=2900000000000,
            pe_ratio=28.5,
            forward_pe=26.0,
            pb_ratio=40.0,
            debt_to_equity=1.5,
            roe=0.35,
            roa=0.15,
            earnings_growth=0.08,
            revenue_growth=0.06,
            free_cash_flow=100000000000,
            operating_cash_flow=115000000000,
        )

        # 3. Run worker on temporary database
        mock_client = MagicMock(spec=YahooClient)
        mock_client.get_company_profile.return_value = mock_profile
        mock_client.get_dividends.return_value = mock_dividends
        mock_client.get_price_history.return_value = mock_prices
        mock_client.get_financials.return_value = mock_financials

        rate_limiter = RateLimiter(base_delay_seconds=0.0, jitter_ratio=0.0)

        with patch("app.sync.worker.SessionLocal", self.SessionLocal):
            worker = SyncWorker(poll_interval=0.01, yahoo_client=mock_client, rate_limiter=rate_limiter)

            # Drain queue (handles SYNC_COMPANY, which enqueues sub-jobs, then drains all sub-jobs)
            max_cycles = 10
            cycles = 0
            while worker.run_once() and cycles < max_cycles:
                cycles += 1

            self.assertGreater(cycles, 0)

        # 4. Verify SQLite state after sync
        with self.SessionLocal() as session:
            company = session.execute(select(Company).where(Company.ticker == "AAPL")).scalar_one_or_none()
            self.assertIsNotNone(company)
            self.assertEqual(company.name, "Apple Inc.")

            metric = session.execute(select(DividendMetric).where(DividendMetric.company_id == company.id)).scalar_one_or_none()
            self.assertIsNotNone(metric)
            self.assertGreater(metric.current_yield or 0.0, 0.0)
            self.assertGreater(metric.quality_score or 0.0, 0.0)

            events = session.execute(select(DividendEvent).where(DividendEvent.company_id == company.id)).scalars().all()
            self.assertEqual(len(events), 6)

        # 5. Verify REST API endpoints
        resp_company = self.client.get("/api/v1/companies/AAPL")
        self.assertEqual(resp_company.status_code, 200)
        self.assertEqual(resp_company.json()["ticker"], "AAPL")

        resp_divs = self.client.get("/api/v1/dividends?ticker=AAPL")
        self.assertEqual(resp_divs.status_code, 200)
        self.assertGreater(len(resp_divs.json()["items"]), 0)

        resp_metric = self.client.get("/api/v1/dividend-metrics/AAPL")
        self.assertEqual(resp_metric.status_code, 200)
        self.assertEqual(resp_metric.json()["ticker"], "AAPL")

        resp_leaders = self.client.get("/api/v1/analytics/quality-leaders")
        self.assertEqual(resp_leaders.status_code, 200)
        self.assertGreaterEqual(len(resp_leaders.json()), 1)

        # 6. Verify Web UI endpoints
        resp_home = self.client.get("/")
        self.assertEqual(resp_home.status_code, 200)
        self.assertIn("Apple Inc.", resp_home.text)

        resp_stocks = self.client.get("/stocks")
        self.assertEqual(resp_stocks.status_code, 200)
        self.assertIn("AAPL", resp_stocks.text)

        resp_detail = self.client.get("/stocks/AAPL")
        self.assertEqual(resp_detail.status_code, 200)
        self.assertIn("Apple Inc.", resp_detail.text)
        self.assertIn("Dividend History", resp_detail.text)

        # 7. Test worker restart / resume behavior:
        # Simulate a crash leaving a job in RUNNING state
        with self.SessionLocal() as session:
            stale_job = SyncJob(
                job_type="SYNC_PRICES",
                ticker="AAPL",
                status="RUNNING",
                locked_by="dead-worker-pid-9999",
                locked_at=datetime(2020, 1, 1),
                updated_at=datetime(2020, 1, 1),
                attempts=1,
                max_attempts=3,
            )
            session.add(stale_job)
            session.commit()
            stale_id = stale_job.id

            # Reap stale jobs
            queue = SyncQueue()
            reaped = queue.reap_stale_jobs(session, stale_timeout_seconds=60)
            session.commit()
            self.assertEqual(reaped, 1)

            # Check that job returned to PENDING / RETRY status
            reaped_job = session.get(SyncJob, stale_id)
            self.assertIn(reaped_job.status, ["PENDING", "RETRY"])
            self.assertIsNone(reaped_job.locked_by)

        # 8. Test live SQLite backup and atomic restore
        backup_file = os.path.join(self.temp_dir, "backup.db")
        restored_file = os.path.join(self.temp_dir, "restored.db")

        # Create live backup while app has open handles
        backup_database(self.db_path, backup_file)
        self.assertTrue(os.path.exists(backup_file))

        # Restore from backup
        restore_database(backup_file, restored_file)
        self.assertTrue(os.path.exists(restored_file))

        # Verify integrity of restored database
        restored_engine = create_engine(f"sqlite:///{restored_file}")
        with restored_engine.connect() as conn:
            check = conn.exec_driver_sql("PRAGMA integrity_check;").scalar()
            self.assertEqual(check, "ok")
            comp_count = conn.exec_driver_sql("SELECT count(*) FROM companies WHERE ticker = 'AAPL';").scalar()
            self.assertEqual(comp_count, 1)
        restored_engine.dispose()


if __name__ == "__main__":
    unittest.main()

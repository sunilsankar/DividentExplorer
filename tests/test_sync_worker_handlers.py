from datetime import date
import unittest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Company, DividendEvent, DividendMetric, Exchange, PriceHistory, SyncJob
from app.db.repositories import (
    CompanyRepository,
    DividendRepository,
    ExchangeRepository,
    FinancialRepository,
    PriceRepository,
)
from app.sync.handlers import dispatch_job, update_analytics_for_company
from app.sync.queue import SyncQueue
from app.sync.rate_limiter import RateLimiter
from app.sync.worker import SyncWorker
from app.yahoo.client import (
    CompanyProfileData,
    DiscoveredTicker,
    DividendEventData,
    FinancialData,
    PriceHistoryData,
    UpstreamThrottledError,
    YahooClient,
)


class TestSyncWorkerHandlers(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        self.queue = SyncQueue()
        self.rate_limiter = RateLimiter(base_delay_seconds=0.0, jitter_ratio=0.0)

        # Mock YahooClient
        self.yahoo = MagicMock(spec=YahooClient)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_handle_sync_exchange(self):
        self.yahoo.discover_tickers.return_value = [
            DiscoveredTicker("T1", "Ticker One", "US"),
            DiscoveredTicker("T2", "Ticker Two", "US"),
        ]

        job = self.queue.enqueue(self.session, job_type="SYNC_EXCHANGE", ticker="US")
        result = dispatch_job(job, self.session, self.yahoo, self.rate_limiter, self.queue)

        self.assertIn("discovered", result.lower())
        # Check companies were added and child jobs have parent_job_id
        comp_repo = CompanyRepository(self.session)
        self.assertIsNotNone(comp_repo.get_by_ticker("T1"))
        self.assertIsNotNone(comp_repo.get_by_ticker("T2"))
        child_jobs = self.session.query(SyncJob).filter_by(parent_job_id=job.id).all()
        self.assertEqual(len(child_jobs), 2)

    def test_handle_sync_company(self):
        self.yahoo.get_company_profile.return_value = CompanyProfileData(
            ticker="AAPL",
            name="Apple Inc.",
            exchange_code="NASDAQ",
            sector="Technology",
            industry="Consumer Electronics",
            country="United States",
            currency="USD",
        )

        job = self.queue.enqueue(self.session, job_type="SYNC_COMPANY", ticker="AAPL")
        result = dispatch_job(job, self.session, self.yahoo, self.rate_limiter, self.queue)
        self.assertIn("AAPL", result)

        comp = CompanyRepository(self.session).get_by_ticker("AAPL")
        self.assertIsNotNone(comp)
        self.assertEqual(comp.sector, "Technology")

    def test_handle_sync_dividends_and_prices(self):
        # Setup company
        comp_repo = CompanyRepository(self.session)
        exch_repo = ExchangeRepository(self.session)
        exch = exch_repo.get_or_create("NYSE", "New York")
        comp, _ = comp_repo.upsert(ticker="JNJ", name="Johnson & Johnson", exchange_id=exch.id)

        # Sync dividends
        self.yahoo.get_dividends.return_value = [
            DividendEventData(ex_date=date(2025, 3, 1), pay_date=None, amount=1.24, status="ACTUAL"),
            DividendEventData(ex_date=date(2025, 6, 1), pay_date=None, amount=1.24, status="ACTUAL"),
        ]
        div_job = self.queue.enqueue(self.session, job_type="SYNC_DIVIDENDS", ticker="JNJ")
        dispatch_job(div_job, self.session, self.yahoo, self.rate_limiter, self.queue)

        events = DividendRepository(self.session).list_events(comp.id)
        self.assertEqual(len(events), 2)

        # Sync prices
        self.yahoo.get_price_history.return_value = [
            PriceHistoryData(date=date(2025, 6, 1), open=150.0, high=155.0, low=149.0, close=152.0, adj_close=152.0, volume=100000)
        ]
        price_job = self.queue.enqueue(self.session, job_type="SYNC_PRICES", ticker="JNJ")
        dispatch_job(price_job, self.session, self.yahoo, self.rate_limiter, self.queue)

        latest = PriceRepository(self.session).get_latest(comp.id)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.close, 152.0)

        # Analytics calculation check
        metric = DividendRepository(self.session).get_metric(comp.id)
        self.assertIsNotNone(metric)
        self.assertGreater(metric.current_yield, 0.0)

    @patch("app.sync.worker.SessionLocal")
    def test_worker_run_once_success_and_throttle(self, mock_session_local):
        mock_session_local.side_effect = self.Session

        worker = SyncWorker(poll_interval=0.1, request_delay=0.0)
        worker.rate_limiter = self.rate_limiter
        worker.yahoo = self.yahoo

        # Enqueue job and commit so other session sees it
        job = worker.queue.enqueue(self.session, job_type="SYNC_COMPANY", ticker="MSFT")
        self.session.commit()

        self.yahoo.get_company_profile.return_value = CompanyProfileData(
            ticker="MSFT",
            name="Microsoft Corp.",
            exchange_code="NASDAQ",
            sector="Technology",
            industry="Software",
            country="United States",
            currency="USD",
        )

        # Run once - should succeed
        processed = worker.run_once()
        self.assertTrue(processed)
        self.session.expire_all()
        updated_job = worker.queue.get_job(self.session, job.id)
        self.assertIsNotNone(updated_job)
        self.assertEqual(updated_job.status, "COMPLETED")

        # Now test throttling handling
        self.yahoo.get_company_profile.side_effect = UpstreamThrottledError("429 Too Many Requests", pause_seconds=10.0)
        job2 = worker.queue.enqueue(self.session, job_type="SYNC_COMPANY", ticker="GOOGL")
        self.session.commit()

        processed2 = worker.run_once()
        self.assertTrue(processed2)
        self.session.expire_all()
        updated_job2 = worker.queue.get_job(self.session, job2.id)
        self.assertIsNotNone(updated_job2)
        self.assertEqual(updated_job2.status, "RETRY")
        self.assertTrue(worker.rate_limiter.is_paused)

    @patch("app.sync.worker.SessionLocal")
    def test_worker_idle_heartbeat_persisted(self, mock_session_local):
        mock_session_local.side_effect = self.Session

        worker = SyncWorker(worker_id="test-idle-worker", poll_interval=0.1, request_delay=0.0)
        processed = worker.run_once()
        self.assertFalse(processed)

        with self.Session() as s:
            from app.sync.queue import WorkerHeartbeatManager
            active = WorkerHeartbeatManager.get_active_workers(s, timeout_seconds=60)
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0].worker_id, "test-idle-worker")
            self.assertEqual(active[0].status, "IDLE")

    def test_handle_sync_exchange_dedups_screener_results(self):
        self.yahoo.discover_tickers.return_value = [
            DiscoveredTicker("JNJ", "Johnson & Johnson", "US"),
            DiscoveredTicker("AAPL", "Apple", "US"),
            DiscoveredTicker("JNJ", "Johnson & Johnson", "US"),
            DiscoveredTicker("JNJ", "Johnson & Johnson", "US"),
        ]
        job = self.queue.enqueue(self.session, job_type="SYNC_EXCHANGE", ticker="US")
        result = dispatch_job(job, self.session, self.yahoo, self.rate_limiter, self.queue)
        child_jobs = self.session.query(SyncJob).filter_by(parent_job_id=job.id).all()
        self.assertEqual(len(child_jobs), 2)
        tickers = {j.ticker for j in child_jobs}
        self.assertEqual(tickers, {"JNJ", "AAPL"})

    def test_handle_sync_exchange_force_enqueues_existing_companies(self):
        # Pre-seed existing exchange, company, and existing previous child job under old parent
        exch = ExchangeRepository(self.session).get_or_create(code="US", name="US")
        comp_repo = CompanyRepository(self.session)
        comp_repo.upsert(ticker="JNJ", name="JNJ", exchange_id=exch.id)
        old_job = self.queue.enqueue(self.session, job_type="SYNC_EXCHANGE", ticker="US")
        self.queue.enqueue(self.session, job_type="SYNC_COMPANY", ticker="JNJ", parent_job_id=old_job.id)
        self.session.commit()

        # Run fresh exchange sync with new parent job
        new_job = self.queue.enqueue(self.session, job_type="SYNC_EXCHANGE", ticker="US", deduplicate=False)
        self.yahoo.discover_tickers.return_value = [DiscoveredTicker("JNJ", "JNJ", "US")]
        dispatch_job(new_job, self.session, self.yahoo, self.rate_limiter, self.queue)

        # Assert new child job is enqueued under new_job.id
        new_children = self.session.query(SyncJob).filter_by(parent_job_id=new_job.id).all()
        self.assertEqual(len(new_children), 1)
        self.assertEqual(new_children[0].ticker, "JNJ")


if __name__ == "__main__":
    unittest.main()

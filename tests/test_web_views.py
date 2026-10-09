"""Tests for Web UI views and templates."""

from datetime import date, datetime, timedelta, timezone
import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    Company,
    DividendEvent,
    DividendMetric,
    Exchange,
    FinancialMetric,
    PriceHistory,
    SyncJob,
    SyncRun,
    WorkerStatus,
    DataChange,
    utcnow,
)
from app.db.session import get_db
from app.main import app


class WebViewsTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

        # Seed data
        nyse = Exchange(code="NYSE", name="New York Stock Exchange", country="USA", currency="USD")
        nasdaq = Exchange(code="NASDAQ", name="NASDAQ Stock Market", country="USA", currency="USD")
        ams = Exchange(code="AMS", name="Euronext Amsterdam", country="Netherlands", currency="EUR")
        self.session.add_all([nyse, nasdaq, ams])
        self.session.flush()

        jnj = Company(
            ticker="JNJ",
            exchange_id=nyse.id,
            name="Johnson & Johnson",
            sector="Healthcare",
            industry="Drug Manufacturers",
            is_active=True,
        )
        msft = Company(
            ticker="MSFT",
            exchange_id=nasdaq.id,
            name="Microsoft Corp",
            sector="Technology",
            industry="Software",
            is_active=True,
        )
        schd = Company(
            ticker="SCHD",
            exchange_id=nyse.id,
            name="Schwab US Dividend Equity ETF",
            sector="Financial Services",
            industry="Exchange Traded Fund",
            asset_type="ETF",
            is_active=True,
        )
        pfe = Company(
            ticker="PFE",
            exchange_id=nyse.id,
            name="Pfizer Inc",
            sector="Healthcare",
            industry="Drug Manufacturers",
            is_active=True,
        )
        self.session.add_all([jnj, msft, schd, pfe])
        self.session.flush()

        metric = DividendMetric(
            company_id=jnj.id,
            current_yield=3.1,
            annual_dividend=4.96,
            growth_3y=5.5,
            payout_ratio=0.55,
            years_paying=20,
            years_growing=15,
            quality_score=85.0,
        )
        pfe_metric = DividendMetric(
            company_id=pfe.id,
            current_yield=5.8,
            annual_dividend=1.68,
            growth_3y=3.2,
            payout_ratio=0.72,
            years_paying=25,
            years_growing=12,
            quality_score=78.0,
        )
        self.session.add_all([metric, pfe_metric])

        event = DividendEvent(
            company_id=jnj.id,
            ex_date=date(2024, 2, 15),
            pay_date=date(2024, 3, 5),
            amount=1.24,
        )
        self.session.add(event)

        price = PriceHistory(
            company_id=jnj.id,
            date=date(2024, 2, 14),
            close=160.0,
            open=159.0,
            high=161.0,
            low=158.5,
            volume=5000000,
        )
        self.session.add(price)

        fin = FinancialMetric(
            company_id=jnj.id,
            calculated_at=datetime(2024, 1, 1),
            market_cap=400000000000,
            pe_ratio=18.5,
            free_cash_flow=15000000000,
        )
        self.session.add(fin)

        worker = WorkerStatus(
            worker_id="test-worker-1",
            status="alive",
            heartbeat_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        self.session.add(worker)

        run = SyncRun(
            run_type="company",
            status="completed",
            items_processed=1,
            items_failed=0,
            started_at=datetime.now(timezone.utc).replace(tzinfo=None),
            completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        self.session.add(run)

        job = SyncJob(
            job_type="SYNC_COMPANY",
            ticker="MSFT",
            status="pending",
            priority=1,
            attempts=0,
            max_attempts=3,
        )
        self.session.add(job)

        change = DataChange(
            entity_type="dividend_metric",
            entity_id=jnj.id,
            field_name="annual_dividend",
            old_value="1.19",
            new_value="1.24",
            detected_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        self.session.add(change)

        self.session.commit()

        def override_get_db():
            s = self.Session()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.session.close()

    def test_dashboard_view(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Market Overview", resp.text)
        self.assertIn("JNJ", resp.text)
        self.assertIn("Dividend Explorer", resp.text)

    def test_stocks_view(self):
        resp = self.client.get("/stocks")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Stock Explorer", resp.text)
        self.assertIn("JNJ", resp.text)
        self.assertIn("MSFT", resp.text)
        self.assertIn("SCHD", resp.text)
        self.assertIn("ETF", resp.text)
        self.assertIn('class="header-search"', resp.text)
        self.assertIn('class="active">Stocks</a>', resp.text)

        # ETFs tab navigation
        resp_etfs = self.client.get("/stocks?asset_type=ETF")
        self.assertEqual(resp_etfs.status_code, 200)
        self.assertIn('class="active">ETFs</a>', resp_etfs.text)

    def test_stocks_table_partial(self):
        resp = self.client.get("/stocks/table?q=JNJ")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("JNJ", resp.text)
        self.assertNotIn("MSFT", resp.text)

        # Filter by ETF
        resp_etf = self.client.get("/stocks/table?asset_type=ETF")
        self.assertEqual(resp_etf.status_code, 200)
        self.assertIn("SCHD", resp_etf.text)
        self.assertNotIn("JNJ", resp_etf.text)

    def test_stocks_sync_state_filter(self):
        # Configure last_synced_at timestamps
        now = utcnow()
        jnj = self.session.query(Company).filter_by(ticker="JNJ").first()
        pfe = self.session.query(Company).filter_by(ticker="PFE").first()
        msft = self.session.query(Company).filter_by(ticker="MSFT").first()
        schd = self.session.query(Company).filter_by(ticker="SCHD").first()

        jnj.last_synced_at = now - timedelta(days=10)
        pfe.last_synced_at = now - timedelta(days=40)
        msft.last_synced_at = now
        schd.last_synced_at = None

        # Add a failed job for PFE
        failed_job = SyncJob(job_type="SYNC_COMPANY", ticker="PFE", status="FAILED")
        self.session.add(failed_job)
        self.session.commit()

        # 1. Never synced: should include SCHD, exclude others
        resp_never = self.client.get("/stocks/table?sync_state=never")
        self.assertEqual(resp_never.status_code, 200)
        self.assertIn("SCHD", resp_never.text)
        self.assertNotIn("JNJ", resp_never.text)
        self.assertNotIn("MSFT", resp_never.text)
        self.assertNotIn("PFE", resp_never.text)

        # 2. Stale > 7d: should include JNJ (10d) and PFE (40d), exclude MSFT (0d) and SCHD (None)
        resp_stale7 = self.client.get("/stocks/table?sync_state=stale_7")
        self.assertEqual(resp_stale7.status_code, 200)
        self.assertIn("JNJ", resp_stale7.text)
        self.assertIn("PFE", resp_stale7.text)
        self.assertNotIn("MSFT", resp_stale7.text)
        self.assertNotIn("SCHD", resp_stale7.text)

        # 3. Stale > 30d: should include PFE (40d), exclude JNJ (10d)
        resp_stale30 = self.client.get("/stocks/table?sync_state=stale_30")
        self.assertEqual(resp_stale30.status_code, 200)
        self.assertIn("PFE", resp_stale30.text)
        self.assertNotIn("JNJ", resp_stale30.text)
        self.assertNotIn("MSFT", resp_stale30.text)

        # 4. Failed job: should include PFE, exclude JNJ/MSFT/SCHD
        resp_failed = self.client.get("/stocks/table?sync_state=failed")
        self.assertEqual(resp_failed.status_code, 200)
        self.assertIn("PFE", resp_failed.text)
        self.assertNotIn("JNJ", resp_failed.text)
        self.assertNotIn("MSFT", resp_failed.text)

        # 5. Full view retains dropdown selection
        resp_view = self.client.get("/stocks?sync_state=stale_7")
        self.assertEqual(resp_view.status_code, 200)
        self.assertIn('value="stale_7" selected', resp_view.text)

    def test_stock_detail_view(self):
        resp = self.client.get("/stocks/JNJ")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Johnson &amp; Johnson", resp.text)
        self.assertIn("3.10%", resp.text)
        self.assertIn("Dividend History", resp.text)
        self.assertIn("Recent Price History", resp.text)
        self.assertIn("dividendChart", resp.text)
        self.assertIn("priceChart", resp.text)
        # Verify peer rendering (PFE is in same industry Drug Manufacturers)
        self.assertIn("Industry Peers (Drug Manufacturers)", resp.text)
        self.assertIn("PFE", resp.text)
        self.assertIn("Pfizer Inc", resp.text)
        self.assertIn("5.80%", resp.text)
        self.assertIn("78.0", resp.text)

    def test_stock_detail_redirect_on_missing(self):
        resp = self.client.get("/stocks/UNKNOWN", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

    def test_industries_view(self):
        resp = self.client.get("/industries")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Industry Explorer", resp.text)
        self.assertIn("Healthcare", resp.text)

    def test_competitors_view(self):
        resp = self.client.get("/competitors?ticker=JNJ")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Competitor &amp; Peer Comparison", resp.text)
        self.assertIn("JNJ", resp.text)

    def test_calendar_view(self):
        resp = self.client.get("/calendar")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Dividend Calendar", resp.text)
        self.assertIn("JNJ", resp.text)

    def test_analytics_view(self):
        resp = self.client.get("/analytics")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Dividend Analytics &amp; Rankings", resp.text)
        self.assertIn("JNJ", resp.text)

    def test_sync_dashboard_view(self):
        resp = self.client.get("/sync")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Ingestion &amp; Sync Dashboard", resp.text)
        self.assertIn("Active Backlog", resp.text)
        self.assertIn("Recent History", resp.text)
        self.assertIn("Sync Logs", resp.text)

    def test_sync_logs_view_and_partial(self):
        # Create a sample completed job and failed job
        job_ok = SyncJob(
            job_type="SYNC_COMPANY",
            ticker="JNJ",
            status="COMPLETED",
            attempts=1,
            max_attempts=3,
        )
        job_failed = SyncJob(
            job_type="SYNC_COMPANY",
            ticker="FAILTICKER",
            status="FAILED",
            attempts=3,
            max_attempts=3,
            error="Rate limit exceeded",
        )
        self.session.add_all([job_ok, job_failed])
        self.session.commit()

        # Direct view /sync/logs
        resp = self.client.get("/sync/logs")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Sync Logs", resp.text)
        self.assertIn("Worker Process Log", resp.text)
        self.assertIn("FAILTICKER", resp.text)
        self.assertIn("Retry", resp.text)

        # Partial HTMX swap /sync/status?tab=logs
        resp_partial = self.client.get("/sync/status?tab=logs")
        self.assertEqual(resp_partial.status_code, 200)
        self.assertIn("Worker Process Log", resp_partial.text)
        self.assertIn("FAILTICKER", resp_partial.text)

    def test_sync_status_partial(self):
        resp = self.client.get("/sync/status?tab=now")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Active Backlog", resp.text)

        resp_recent = self.client.get("/sync/status?tab=recent")
        self.assertEqual(resp_recent.status_code, 200)
        self.assertIn("Recent History", resp_recent.text)

    def test_reap_stuck_and_retry_throttled(self):
        resp = self.client.post("/sync/reap-stuck")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("sync-status-container", resp.text)

        resp2 = self.client.post("/sync/retry-throttled")
        self.assertEqual(resp2.status_code, 200)
        self.assertIn("sync-status-container", resp2.text)

    def test_trigger_sync(self):
        resp = self.client.post("/sync/trigger", data={"ticker": "AAPL"})
        self.assertEqual(resp.status_code, 200)
        # Check job enqueued in db
        job = self.session.query(SyncJob).filter_by(ticker="AAPL").first()
        self.assertIsNotNone(job)

    def test_sync_exchanges_view(self):
        resp = self.client.get("/sync/exchanges")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Exchange Synchronization", resp.text)
        self.assertIn("Sync All Exchanges", resp.text)
        self.assertIn("NYSE", resp.text)
        self.assertIn("NASDAQ", resp.text)
        self.assertIn("AMS", resp.text)
        self.assertIn("EUR", resp.text)
        self.assertIn("Sync Progress", resp.text)

    def test_trigger_all_exchanges(self):
        resp = self.client.post("/sync/trigger-all-exchanges")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Exchange Synchronization", resp.text)
        jobs = self.session.query(SyncJob).filter_by(job_type="SYNC_EXCHANGE").all()
        self.assertGreaterEqual(len(jobs), 3)

    def test_changes_view(self):
        resp = self.client.get("/changes")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Data Change Detection", resp.text)
        self.assertIn("dividend_increase", resp.text)
        self.assertIn("JNJ", resp.text)

    def test_health_check(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_trigger_exchange_sync_shows_dedup_hint(self):
        resp1 = self.client.post("/sync/trigger", data={"exchange": "AMS"})
        self.assertEqual(resp1.status_code, 200)
        self.assertNotIn("already queued/running", resp1.text)

        resp2 = self.client.post("/sync/trigger", data={"exchange": "AMS"})
        self.assertEqual(resp2.status_code, 200)
        self.assertIn("already queued/running", resp2.text)

    def test_force_exchange_sync_cancels_in_flight(self):
        self.client.post("/sync/trigger", data={"exchange": "AMS"})
        j1 = self.session.query(SyncJob).filter_by(job_type="SYNC_EXCHANGE", ticker="AMS").first()
        self.assertEqual(j1.status, "PENDING")

        resp = self.client.post("/sync/force", data={"exchange": "AMS"})
        self.assertEqual(resp.status_code, 200)

        # Refresh session to see db changes
        self.session.expire_all()
        self.session.refresh(j1)
        self.assertEqual(j1.status, "CANCELLED")

        j2 = self.session.query(SyncJob).filter_by(job_type="SYNC_EXCHANGE", ticker="AMS", status="PENDING").first()
        self.assertIsNotNone(j2)
        self.assertNotEqual(j1.id, j2.id)


if __name__ == "__main__":
    unittest.main()

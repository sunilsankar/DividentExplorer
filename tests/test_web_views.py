"""Tests for Web UI views and templates."""

from datetime import date, datetime, timezone
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
        self.session.add_all([jnj, msft, schd])
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
        self.session.add(metric)

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

    def test_stock_detail_view(self):
        resp = self.client.get("/stocks/JNJ")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Johnson &amp; Johnson", resp.text)
        self.assertIn("3.10%", resp.text)
        self.assertIn("Dividend History", resp.text)
        self.assertIn("Recent Price History", resp.text)
        self.assertIn("dividendChart", resp.text)
        self.assertIn("priceChart", resp.text)

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
        self.assertIn("test-worker-1", resp.text)
        self.assertIn("MSFT", resp.text)

    def test_sync_status_partial(self):
        resp = self.client.get("/sync/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("test-worker-1", resp.text)

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
        self.assertIn("NYSE", resp.text)
        self.assertIn("NASDAQ", resp.text)
        self.assertIn("AMS", resp.text)
        self.assertIn("EUR", resp.text)
        self.assertIn("Sync Progress", resp.text)

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


if __name__ == "__main__":
    unittest.main()

"""Tests for /api/v1 REST endpoints."""

from datetime import date
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import router
from app.db.models import Base, Company, DividendEvent, DividendMetric, Exchange, FinancialMetric, PriceHistory, SyncJob, SyncRun, WorkerStatus
from app.db.session import get_db


class ApiRoutesTestCase(unittest.TestCase):
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
        nasdaq = Exchange(code="NASDAQ", name="Nasdaq Stock Market", country="USA", currency="USD")
        self.session.add_all([nyse, nasdaq])
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

        # Dividend metric
        jnj_metric = DividendMetric(
            company_id=jnj.id,
            current_yield=0.031,
            trailing_yield=0.030,
            forward_yield=0.032,
            annual_dividend=4.96,
            growth_1y=0.05,
            growth_3y=0.06,
            years_paying=60,
            years_growing=60,
            quality_score=92.0,
        )
        self.session.add(jnj_metric)

        # Dividend events
        div_ev = DividendEvent(
            company_id=jnj.id,
            ex_date=date(2025, 2, 18),
            record_date=date(2025, 2, 19),
            pay_date=date(2025, 3, 4),
            amount=1.24,
            status="ACTUAL",
        )
        self.session.add(div_ev)

        # Price history
        price = PriceHistory(
            company_id=jnj.id,
            date=date(2025, 2, 18),
            open=160.0,
            high=162.0,
            low=159.5,
            close=161.0,
            adj_close=161.0,
            volume=5000000,
        )
        self.session.add(price)

        # Financial metric
        fin = FinancialMetric(
            company_id=jnj.id,
            market_cap=400000000000.0,
            pe_ratio=24.5,
        )
        self.session.add(fin)

        # Sync job & run & worker status
        job = SyncJob(job_type="SYNC_COMPANY", ticker="JNJ", status="COMPLETED")
        run = SyncRun(run_type="SYNC_COMPANY", status="COMPLETED", items_processed=1)
        worker = WorkerStatus(worker_id="test-worker-1", status="IDLE")
        self.session.add_all([job, run, worker])
        self.session.commit()

        # Build app with dependency override
        self.app = FastAPI()
        self.app.include_router(router)

        def _override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        self.app.dependency_overrides[get_db] = _override_get_db
        self.client = TestClient(self.app)

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(self.engine)

    def test_list_and_get_exchanges(self):
        resp = self.client.get("/api/v1/exchanges")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        codes = [e["code"] for e in data]
        self.assertIn("NYSE", codes)

        resp_single = self.client.get("/api/v1/exchanges/NYSE")
        self.assertEqual(resp_single.status_code, 200)
        self.assertEqual(resp_single.json()["code"], "NYSE")

        resp_404 = self.client.get("/api/v1/exchanges/UNKNOWN")
        self.assertEqual(resp_404.status_code, 404)

    def test_list_and_get_companies(self):
        resp = self.client.get("/api/v1/companies")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 3)
        self.assertEqual(len(data["items"]), 3)

        # Asset type filter (ETF vs STOCK)
        resp_etf = self.client.get("/api/v1/companies?asset_type=ETF")
        self.assertEqual(resp_etf.status_code, 200)
        self.assertEqual(resp_etf.json()["total"], 1)
        self.assertEqual(resp_etf.json()["items"][0]["ticker"], "SCHD")
        self.assertEqual(resp_etf.json()["items"][0]["asset_type"], "ETF")

        resp_stock = self.client.get("/api/v1/companies?asset_type=STOCK")
        self.assertEqual(resp_stock.status_code, 200)
        self.assertEqual(resp_stock.json()["total"], 2)

        # Search filter
        resp_search = self.client.get("/api/v1/companies?search=Johnson")
        self.assertEqual(resp_search.status_code, 200)
        self.assertEqual(resp_search.json()["total"], 1)
        self.assertEqual(resp_search.json()["items"][0]["ticker"], "JNJ")

        # Detail endpoint
        resp_detail = self.client.get("/api/v1/companies/JNJ")
        self.assertEqual(resp_detail.status_code, 200)
        detail = resp_detail.json()
        self.assertEqual(detail["ticker"], "JNJ")
        self.assertEqual(detail["asset_type"], "STOCK")
        self.assertIsNotNone(detail["dividend_metric"])
        self.assertAlmostEqual(detail["dividend_metric"]["quality_score"], 92.0)
        self.assertIsNotNone(detail["latest_price"])

        resp_404 = self.client.get("/api/v1/companies/UNKNOWN")
        self.assertEqual(resp_404.status_code, 404)

    def test_dividends_and_metrics(self):
        resp = self.client.get("/api/v1/dividends?ticker=JNJ")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["amount"], 1.24)

        resp_metrics = self.client.get("/api/v1/dividend-metrics/JNJ")
        self.assertEqual(resp_metrics.status_code, 200)
        metrics = resp_metrics.json()
        self.assertEqual(metrics["years_paying"], 60)

    def test_prices_and_financials(self):
        resp_prices = self.client.get("/api/v1/prices/JNJ")
        self.assertEqual(resp_prices.status_code, 200)
        prices = resp_prices.json()
        self.assertEqual(len(prices), 1)
        self.assertEqual(prices[0]["close"], 161.0)

        resp_fin = self.client.get("/api/v1/financials/JNJ")
        self.assertEqual(resp_fin.status_code, 200)
        self.assertEqual(resp_fin.json()["pe_ratio"], 24.5)

    def test_industries_and_competitors(self):
        resp_ind = self.client.get("/api/v1/industries")
        self.assertEqual(resp_ind.status_code, 200)
        inds = resp_ind.json()
        self.assertGreater(len(inds), 0)

        resp_comp = self.client.get("/api/v1/competitors/JNJ")
        self.assertEqual(resp_comp.status_code, 200)
        comp_data = resp_comp.json()
        self.assertEqual(comp_data["target"]["ticker"], "JNJ")

    def test_analytics_endpoints(self):
        resp_yields = self.client.get("/api/v1/analytics/top-yields")
        self.assertEqual(resp_yields.status_code, 200)
        self.assertGreater(len(resp_yields.json()), 0)

        resp_growth = self.client.get("/api/v1/analytics/dividend-growth")
        self.assertEqual(resp_growth.status_code, 200)
        self.assertGreater(len(resp_growth.json()), 0)

        resp_quality = self.client.get("/api/v1/analytics/quality-leaders")
        self.assertEqual(resp_quality.status_code, 200)
        self.assertGreater(len(resp_quality.json()), 0)

    def test_sync_status_and_jobs(self):
        resp_sync = self.client.get("/api/v1/sync/status")
        self.assertEqual(resp_sync.status_code, 200)
        sync_data = resp_sync.json()
        self.assertIn("workers", sync_data)
        self.assertIn("queue_stats", sync_data)

        resp_jobs = self.client.get("/api/v1/sync/jobs")
        self.assertEqual(resp_jobs.status_code, 200)
        self.assertEqual(resp_jobs.json()["total"], 1)


if __name__ == "__main__":
    unittest.main()

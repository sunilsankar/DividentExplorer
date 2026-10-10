from datetime import date
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base
from app.db.repositories import CompanyRepository, ExchangeRepository, PriceRepository
from app.services.stock_service import StockService
from app.services.sync_service import SyncService


class ServicesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.session: Session = self.session_factory()
        self.stock_service = StockService(self.session)
        self.sync_service = SyncService(self.session)

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_stock_service_crud_and_detail(self) -> None:
        ex = ExchangeRepository(self.session).upsert(code="NYSE", name="New York Stock Exchange")
        comp, _ = CompanyRepository(self.session).upsert(
            ticker="IBM",
            exchange_id=ex.id,
            name="International Business Machines",
            sector="Technology",
            industry="IT Services",
        )
        PriceRepository(self.session).upsert_price(
            company_id=comp.id,
            price_date=date(2025, 1, 15),
            close_price=220.0,
        )
        self.session.commit()

        # List companies
        companies = self.stock_service.list_companies()
        self.assertEqual(len(companies), 1)

        # Count companies
        count = self.stock_service.count_companies()
        self.assertEqual(count, 1)

        # Get detail
        detail = self.stock_service.get_company_detail("IBM")
        self.assertIsNotNone(detail)
        self.assertEqual(detail["company"].ticker, "IBM")
        self.assertEqual(detail["exchange"].code, "NYSE")
        self.assertIsNotNone(detail["latest_price"])
        self.assertEqual(detail["latest_price"].close, 220.0)

    def test_sync_service_enqueue_and_stats(self) -> None:
        job = self.sync_service.enqueue_ticker_sync("AAPL")
        self.session.commit()
        self.assertIsNotNone(job.id)
        self.assertEqual(job.ticker, "AAPL")

        stats = self.sync_service.get_queue_stats()
        self.assertEqual(stats["PENDING"], 1)

        recent_jobs = self.sync_service.get_recent_jobs()
        self.assertEqual(len(recent_jobs), 1)

    def test_sync_service_exchange_progress(self) -> None:
        ex_job, dedup = self.sync_service.enqueue_exchange_sync("AMS")
        self.assertFalse(dedup)
        self.session.commit()

        progress = self.sync_service.get_exchange_progress("AMS")
        self.assertEqual(progress["total"], 0)
        self.assertEqual(progress["percent"], 0.0)

        child1 = self.sync_service.queue.enqueue(
            self.session, "SYNC_COMPANY", ticker="ASML.AS", parent_job_id=ex_job.id
        )
        child2 = self.sync_service.queue.enqueue(
            self.session, "SYNC_COMPANY", ticker="INGA.AS", parent_job_id=ex_job.id
        )
        self.session.commit()

        progress = self.sync_service.get_exchange_progress("AMS")
        self.assertEqual(progress["total"], 2)
        self.assertEqual(progress["pending"], 2)
        self.assertEqual(progress["percent"], 0.0)

        self.sync_service.queue.complete_job(self.session, child1.id)
        self.session.commit()

        progress = self.sync_service.get_exchange_progress("AMS")
        self.assertEqual(progress["completed"], 1)
        self.assertEqual(progress["percent"], 50.0)

    def test_get_stuck_running_count_and_all_exchange_progress(self):
        ExchangeRepository(self.session).upsert(code="AMS", name="Euronext Amsterdam")
        self.session.commit()

        # Test get_all_exchange_progress returns list with AMS
        all_ex = self.sync_service.get_all_exchange_progress()
        self.assertTrue(any(e["code"] == "AMS" for e in all_ex))

        # Test get_stuck_running_count
        count_zero = self.sync_service.get_stuck_running_count(threshold_seconds=300)
        self.assertEqual(count_zero, 0)

    def test_sync_service_enqueue_exchange_sync_dedup_flag(self):
        job1, dedup1 = self.sync_service.enqueue_exchange_sync("AMS")
        self.assertFalse(dedup1)

        job2, dedup2 = self.sync_service.enqueue_exchange_sync("AMS")
        self.assertTrue(dedup2)
        self.assertEqual(job1.id, job2.id)

        # Cancel in flight and check dedup=False
        cancelled = self.sync_service.cancel_in_flight_exchange_syncs("AMS")
        self.assertEqual(cancelled, 1)

        job3, dedup3 = self.sync_service.enqueue_exchange_sync("AMS")
        self.assertFalse(dedup3)
        self.assertNotEqual(job1.id, job3.id)

    def test_sync_service_cleanup_unclassified(self):
        ex = ExchangeRepository(self.session).upsert(code="NYSE", name="New York Stock Exchange")
        self.session.commit()

        from datetime import datetime, timezone, timedelta
        from app.db.models import Company
        old_time = datetime.now(timezone.utc) - timedelta(hours=48)

        unclass = Company(
            ticker="STALEUNCLASS",
            exchange_id=ex.id,
            name="Stale Unclassified",
            sector=None,
            industry=None,
            country=None,
            currency=None,
            asset_type="STOCK",
            created_at=old_time,
            last_synced_at=old_time,
        )
        self.session.add(unclass)
        self.session.commit()

        count = self.sync_service.count_unclassified(grace_hours=24)
        self.assertEqual(count, 1)

        deleted = self.sync_service.cleanup_unclassified(grace_hours=24)
        self.assertEqual(deleted, 1)
        self.assertEqual(self.sync_service.count_unclassified(grace_hours=24), 0)

    def test_search_companies_with_exchange_filter_and_base_ticker_detail(self):
        ex_ams = ExchangeRepository(self.session).upsert(code="AMS", name="Euronext Amsterdam")
        ex_nyse = ExchangeRepository(self.session).upsert(code="NYSE", name="New York Stock Exchange")
        comp_repo = CompanyRepository(self.session)
        comp_repo.upsert(ticker="AD.AS", exchange_id=ex_ams.id, name="Ahold Delhaize", sector="Consumer Defensive")
        comp_repo.upsert(ticker="ADP", exchange_id=ex_nyse.id, name="Automatic Data Processing", sector="Technology")
        self.session.commit()

        # Search without exchange filter finds both
        all_res = self.stock_service.search_companies(query="AD")
        self.assertEqual(all_res["total"], 2)
        self.assertEqual(all_res["items"][0].ticker, "AD.AS")

        # Search with AMS filter finds only AD.AS
        ams_res = self.stock_service.search_companies(query="AD", exchange="AMS")
        self.assertEqual(ams_res["total"], 1)
        self.assertEqual(ams_res["items"][0].ticker, "AD.AS")

        # Search with NYSE filter finds only ADP
        nyse_res = self.stock_service.search_companies(query="AD", exchange="NYSE")
        self.assertEqual(nyse_res["total"], 1)
        self.assertEqual(nyse_res["items"][0].ticker, "ADP")

        # get_company_detail("AD") resolves to AD.AS
        detail = self.stock_service.get_company_detail("AD")
        self.assertIsNotNone(detail)
        self.assertEqual(detail["company"].ticker, "AD.AS")


if __name__ == "__main__":
    unittest.main()

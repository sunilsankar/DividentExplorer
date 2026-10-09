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
        ex_job = self.sync_service.enqueue_exchange_sync("AMS")
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


if __name__ == "__main__":
    unittest.main()

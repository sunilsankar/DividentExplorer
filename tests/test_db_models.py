import unittest
import warnings
from datetime import date
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.db.models import (
    Company,
    CompanyRelationship,
    DataChange,
    DividendEvent,
    DividendMetric,
    Exchange,
    FinancialMetric,
    PriceHistory,
    SyncJob,
    SyncRun,
    SyncState,
    WorkerStatus,
)

warnings.filterwarnings("ignore", category=ResourceWarning)


class DatabaseModelsTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_create_exchange_and_company(self):
        exchange = Exchange(code="NYSE", name="New York Stock Exchange", country="USA", currency="USD")
        self.session.add(exchange)
        self.session.commit()

        company = Company(
            ticker="JNJ",
            exchange_id=exchange.id,
            name="Johnson & Johnson",
            sector="Healthcare",
            industry="Drug Manufacturers - General",
            country="USA",
            currency="USD",
        )
        self.session.add(company)
        self.session.commit()

        retrieved = self.session.query(Company).filter_by(ticker="JNJ").first()
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.exchange.code, "NYSE")
        self.assertEqual(len(exchange.companies), 1)

    def test_foreign_key_constraint(self):
        invalid_company = Company(
            ticker="BAD",
            exchange_id=9999,  # Non-existent exchange
            name="Bad Company",
        )
        self.session.add(invalid_company)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_unique_ticker_per_exchange_constraint(self):
        exchange = Exchange(code="NASDAQ", name="Nasdaq")
        self.session.add(exchange)
        self.session.commit()

        c1 = Company(ticker="AAPL", exchange_id=exchange.id, name="Apple Inc.")
        c2 = Company(ticker="AAPL", exchange_id=exchange.id, name="Apple Inc. Duplicate")
        self.session.add(c1)
        self.session.commit()

        self.session.add(c2)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_company_child_models_and_cascade(self):
        exchange = Exchange(code="US", name="US Market")
        self.session.add(exchange)
        self.session.commit()

        company = Company(ticker="MSFT", exchange_id=exchange.id, name="Microsoft")
        self.session.add(company)
        self.session.commit()

        div_event = DividendEvent(
            company_id=company.id,
            ex_date=date(2026, 2, 18),
            pay_date=date(2026, 3, 12),
            amount=0.83,
            currency="USD",
            status="ACTUAL",
        )
        div_metric = DividendMetric(
            company_id=company.id,
            current_yield=0.0075,
            annual_dividend=3.32,
            payout_ratio=0.25,
        )
        fin_metric = FinancialMetric(
            company_id=company.id,
            market_cap=3200000000000.0,
            pe_ratio=34.5,
        )
        price = PriceHistory(
            company_id=company.id,
            date=date(2026, 3, 1),
            close=420.0,
        )
        self.session.add_all([div_event, div_metric, fin_metric, price])
        self.session.commit()

        self.assertEqual(len(company.dividend_events), 1)
        self.assertIsNotNone(company.dividend_metric)
        self.assertIsNotNone(company.financial_metric)
        self.assertEqual(len(company.price_history), 1)

        # Deleting company cascades to events and metrics
        self.session.delete(company)
        self.session.commit()

        self.assertEqual(self.session.query(DividendEvent).count(), 0)
        self.assertEqual(self.session.query(DividendMetric).count(), 0)
        self.assertEqual(self.session.query(FinancialMetric).count(), 0)
        self.assertEqual(self.session.query(PriceHistory).count(), 0)

    def test_sync_jobs_and_operational_models(self):
        job = SyncJob(
            job_type="COMPANY",
            ticker="PG",
            priority=5,
            status="PENDING",
        )
        run = SyncRun(run_type="DAILY_DISCOVERY")
        status = WorkerStatus(worker_id="worker-1", status="RUNNING")
        state = SyncState(key="last_discovery_time", value_json='{"timestamp": "2026-10-09"}')
        change = DataChange(
            entity_type="Company",
            entity_id=1,
            field_name="sector",
            old_value="Consumer Goods",
            new_value="Consumer Defensive",
        )
        self.session.add_all([job, run, status, state, change])
        self.session.commit()

        child_job = SyncJob(
            job_type="DIVIDENDS",
            ticker="PG",
            priority=7,
            status="PENDING",
            parent_job_id=job.id,
        )
        self.session.add(child_job)
        self.session.commit()

        self.assertEqual(self.session.query(SyncJob).filter_by(ticker="PG").count(), 2)
        self.assertEqual(self.session.query(SyncJob).filter_by(parent_job_id=job.id).count(), 1)
        self.assertEqual(self.session.query(SyncRun).count(), 1)
        self.assertEqual(self.session.query(WorkerStatus).filter_by(worker_id="worker-1").count(), 1)
        self.assertEqual(self.session.query(SyncState).filter_by(key="last_discovery_time").count(), 1)
        self.assertEqual(self.session.query(DataChange).filter_by(field_name="sector").count(), 1)


if __name__ == "__main__":
    unittest.main()

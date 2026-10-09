import unittest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Company, CompanyRelationship, DividendEvent, DividendMetric
from scripts.seed_demo_data import DEMO_STOCKS, seed


class SeedScriptTestCase(unittest.TestCase):
    def test_seed_creates_demo_data(self) -> None:
        # Isolated in-memory engine with StaticPool
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        with patch("scripts.seed_demo_data.SessionLocal", TestSessionLocal):
            with patch("scripts.seed_demo_data.init_db", lambda: None):
                seed()

        session = TestSessionLocal()
        try:
            companies = session.query(Company).all()
            self.assertEqual(len(companies), len(DEMO_STOCKS))

            for comp in companies:
                self.assertIsNotNone(comp.exchange_id)
                self.assertIsNotNone(comp.sector)
                self.assertIsNotNone(comp.industry)

                events = session.query(DividendEvent).filter_by(company_id=comp.id).all()
                self.assertEqual(len(events), 8)

                metric = session.query(DividendMetric).filter_by(company_id=comp.id).first()
                self.assertIsNotNone(metric)
                self.assertIsNotNone(metric.annual_dividend)
                self.assertIsNotNone(metric.dividend_quality_score)

            relationships = session.query(CompanyRelationship).all()
            self.assertGreaterEqual(len(relationships), 2)
        finally:
            session.close()
            Base.metadata.drop_all(bind=engine)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()

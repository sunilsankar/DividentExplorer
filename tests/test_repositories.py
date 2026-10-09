from datetime import date, datetime, timezone
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base
from app.db.repositories import (
    ChangeRepository,
    CompanyRepository,
    DividendRepository,
    ExchangeRepository,
    FinancialRepository,
    PriceRepository,
    SyncStateRepository,
)


class RepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.session: Session = self.session_factory()

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_exchange_repository(self) -> None:
        repo = ExchangeRepository(self.session)

        # Upsert new
        ex = repo.upsert(code="NYSE", name="New York Stock Exchange", country="USA")
        self.session.commit()
        self.assertIsNotNone(ex.id)
        self.assertEqual(ex.code, "NYSE")

        # Upsert update
        ex2 = repo.upsert(code="nyse", name="NYSE Updated", country="USA")
        self.session.commit()
        self.assertEqual(ex.id, ex2.id)
        self.assertEqual(ex2.name, "NYSE Updated")

        # List all
        exchanges = repo.list_all()
        self.assertEqual(len(exchanges), 1)

        # Get by code
        found = repo.get_by_code("NYSE")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, ex.id)

    def test_company_repository(self) -> None:
        ex_repo = ExchangeRepository(self.session)
        ex = ex_repo.upsert(code="NASDAQ", name="Nasdaq")
        self.session.commit()

        comp_repo = CompanyRepository(self.session)

        # Upsert new company
        company, created = comp_repo.upsert(
            ticker="AAPL",
            exchange_id=ex.id,
            name="Apple Inc.",
            sector="Technology",
            industry="Consumer Electronics",
        )
        self.session.commit()
        self.assertTrue(created)
        self.assertEqual(company.ticker, "AAPL")

        # Update existing
        company2, created2 = comp_repo.upsert(
            ticker="aapl",
            exchange_id=ex.id,
            name="Apple Inc. Modified",
            sector="Technology",
            industry="Consumer Electronics",
        )
        self.session.commit()
        self.assertFalse(created2)
        self.assertEqual(company.id, company2.id)
        self.assertEqual(company2.name, "Apple Inc. Modified")

        # Search & count
        results = comp_repo.list_companies(search="apple")
        self.assertEqual(len(results), 1)
        count = comp_repo.count_companies(search="apple")
        self.assertEqual(count, 1)

        # Sectors & industries
        sectors = comp_repo.list_sectors()
        self.assertIn("Technology", sectors)

        # Upsert ETF and filter by asset_type
        etf, etf_created = comp_repo.upsert(
            ticker="SCHD",
            exchange_id=ex.id,
            name="Schwab US Dividend Equity ETF",
            sector="Financial Services",
            industry="Exchange Traded Fund",
            asset_type="ETF",
        )
        self.session.commit()
        self.assertTrue(etf_created)
        self.assertEqual(etf.asset_type, "ETF")

        stock_results = comp_repo.list_companies(asset_type="STOCK")
        self.assertEqual(len(stock_results), 1)
        self.assertEqual(stock_results[0].ticker, "AAPL")

        etf_results = comp_repo.list_companies(asset_type="ETF")
        self.assertEqual(len(etf_results), 1)
        self.assertEqual(etf_results[0].ticker, "SCHD")
        self.assertEqual(comp_repo.count_companies(asset_type="ETF"), 1)
        industries = comp_repo.list_industries(sector="Technology")
        self.assertIn("Consumer Electronics", industries)

        # Mark synced
        comp_repo.mark_synced(company.id)
        self.session.commit()
        self.assertIsNotNone(company.last_synced_at)

    def test_dividend_repository(self) -> None:
        ex = ExchangeRepository(self.session).upsert(code="NYSE", name="NYSE")
        comp, _ = CompanyRepository(self.session).upsert(
            ticker="JNJ", exchange_id=ex.id, name="Johnson & Johnson"
        )
        self.session.commit()

        div_repo = DividendRepository(self.session)

        # Upsert event
        event1, created1 = div_repo.upsert_event(
            company_id=comp.id,
            ex_date=date(2025, 2, 18),
            pay_date=date(2025, 3, 4),
            amount=1.24,
            frequency="quarterly",
        )
        self.session.commit()
        self.assertTrue(created1)

        # Deduplicate identical event
        event2, created2 = div_repo.upsert_event(
            company_id=comp.id,
            ex_date=date(2025, 2, 18),
            pay_date=date(2025, 3, 4),
            amount=1.24,
            frequency="quarterly",
        )
        self.session.commit()
        self.assertFalse(created2)
        self.assertEqual(event1.id, event2.id)

        # Latest event
        latest = div_repo.get_latest_event(comp.id)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.amount, 1.24)

        # Upsert metric
        metric = div_repo.upsert_metric(
            company_id=comp.id,
            current_yield=3.1,
            annual_dividend=4.96,
            years_growing=62,
        )
        self.session.commit()
        self.assertEqual(metric.current_yield, 3.1)
        self.assertEqual(metric.years_growing, 62)

    def test_price_repository(self) -> None:
        ex = ExchangeRepository(self.session).upsert(code="NYSE", name="NYSE")
        comp, _ = CompanyRepository(self.session).upsert(
            ticker="PG", exchange_id=ex.id, name="Procter & Gamble"
        )
        self.session.commit()

        price_repo = PriceRepository(self.session)

        p1, created1 = price_repo.upsert_price(
            company_id=comp.id,
            price_date=date(2025, 1, 10),
            close_price=160.0,
            volume=5000000,
        )
        self.session.commit()
        self.assertTrue(created1)

        p2, created2 = price_repo.upsert_price(
            company_id=comp.id,
            price_date=date(2025, 1, 10),
            close_price=161.5,
            volume=5100000,
        )
        self.session.commit()
        self.assertFalse(created2)
        self.assertEqual(p1.id, p2.id)
        self.assertEqual(p2.close, 161.5)

        latest = price_repo.get_latest_price(comp.id)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.close, 161.5)

    def test_financial_repository(self) -> None:
        ex = ExchangeRepository(self.session).upsert(code="NYSE", name="NYSE")
        comp, _ = CompanyRepository(self.session).upsert(
            ticker="KO", exchange_id=ex.id, name="Coca-Cola"
        )
        self.session.commit()

        fin_repo = FinancialRepository(self.session)
        metric = fin_repo.upsert_metric(
            company_id=comp.id,
            market_cap=250000000000.0,
            pe_ratio=24.5,
            payout_ratio=0.72,
        )
        self.session.commit()
        self.assertEqual(metric.pe_ratio, 24.5)

        # Update metric
        metric2 = fin_repo.upsert_metric(
            company_id=comp.id,
            pe_ratio=23.8,
        )
        self.session.commit()
        self.assertEqual(metric.id, metric2.id)
        self.assertEqual(metric2.pe_ratio, 23.8)

    def test_change_repository(self) -> None:
        repo = ChangeRepository(self.session)

        # Test single change with optional reason kwarg
        change = repo.record_change(
            entity_type="Company",
            entity_id=1,
            field_name="sector",
            old_value="Old Sector",
            new_value="New Sector",
            reason="Sector reclassification",
        )
        self.session.commit()
        self.assertIsNotNone(change)

        # Identical value should not record a change
        no_change = repo.record_change(
            entity_type="Company",
            entity_id=1,
            field_name="sector",
            old_value="New Sector",
            new_value="New Sector",
        )
        self.assertIsNone(no_change)

        # Test record_diff
        old_data = {"yield": 3.0, "payout": 0.50, "same": "x"}
        new_data = {"yield": 3.5, "payout": 0.50, "same": "x", "extra": "y"}
        diffs = repo.record_diff("DividendMetric", 1, old_data, new_data)
        self.session.commit()
        self.assertEqual(len(diffs), 2)  # yield changed, extra added

        recent = repo.list_recent(limit=10)
        self.assertEqual(len(recent), 3)

    def test_sync_state_repository(self) -> None:
        repo = SyncStateRepository(self.session)
        repo.set_value("last_sync_key", '{"status": "ok"}')
        self.session.commit()

        val = repo.get_value("last_sync_key")
        self.assertEqual(val, '{"status": "ok"}')

        repo.set_value("last_sync_key", '{"status": "updated"}')
        self.session.commit()
        self.assertEqual(repo.get_value("last_sync_key"), '{"status": "updated"}')


if __name__ == "__main__":
    unittest.main()

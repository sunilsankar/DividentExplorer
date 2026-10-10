from datetime import date, datetime, timedelta, timezone
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, Company, CompanyRelationship, DividendEvent, PriceHistory, SyncJob
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

    def test_unclassified_count_and_delete(self) -> None:
        ex_repo = ExchangeRepository(self.session)
        comp_repo = CompanyRepository(self.session)
        ex = ex_repo.upsert(code="NYSE", name="New York Stock Exchange", country="USA")
        self.session.commit()

        old_time = datetime.now(timezone.utc) - timedelta(hours=48)
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=30)

        # 1. Normal classified stock
        c_good, _ = comp_repo.upsert(
            ticker="GOOD",
            exchange_id=ex.id,
            name="Good Stock",
            sector="Technology",
            industry="Software",
            country="USA",
            currency="USD",
            asset_type="STOCK",
        )
        c_good.last_synced_at = old_time

        # 2. Old unclassified stock (missing sector)
        c_old_unclass = Company(
            ticker="BAD1",
            exchange_id=ex.id,
            name="Unclassified Stock 1",
            sector=None,
            industry=None,
            country="USA",
            currency="USD",
            asset_type="STOCK",
            created_at=old_time,
            last_synced_at=old_time,
        )
        self.session.add(c_old_unclass)

        # 3. Recent unclassified stock (< 24h grace period)
        c_recent_unclass = Company(
            ticker="BAD2",
            exchange_id=ex.id,
            name="Recent Unclassified Stock 2",
            sector=None,
            industry=None,
            country=None,
            currency=None,
            asset_type="STOCK",
            created_at=recent_time,
            last_synced_at=None,
        )
        self.session.add(c_recent_unclass)

        # 4. Legitimate ETF (no sector/industry/country, but valid ETF)
        c_etf = Company(
            ticker="SCHD",
            exchange_id=ex.id,
            name="Schwab US Dividend Equity ETF",
            sector=None,
            industry=None,
            country=None,
            currency="USD",
            asset_type="ETF",
            created_at=old_time,
            last_synced_at=old_time,
        )
        self.session.add(c_etf)

        # 5. Invalid ETF (missing currency)
        c_bad_etf = Company(
            ticker="BADETF",
            exchange_id=ex.id,
            name="Corrupted ETF",
            sector=None,
            industry=None,
            country=None,
            currency=None,
            asset_type="ETF",
            created_at=old_time,
            last_synced_at=old_time,
        )
        self.session.add(c_bad_etf)
        self.session.commit()

        # Add child records for c_old_unclass to verify cascading / child cleanup
        self.session.add(CompanyRelationship(company_id=c_old_unclass.id, related_company_id=c_good.id, relationship_type="competitor"))
        self.session.add(DividendEvent(company_id=c_old_unclass.id, ex_date=date(2025, 1, 1), amount=1.0, currency="USD"))
        self.session.add(PriceHistory(company_id=c_old_unclass.id, date=date(2025, 1, 1), close=10.0))
        self.session.add(SyncJob(job_type="SYNC_COMPANY", ticker="BAD1", entity_type="company", entity_id=c_old_unclass.id))
        self.session.commit()

        # Count with 24h grace period: should find BAD1 and BADETF (c_recent_unclass is within grace; SCHD is valid ETF)
        count = comp_repo.count_unclassified(grace_hours=24)
        self.assertEqual(count, 2)

        # Delete with 24h grace period
        deleted = comp_repo.delete_unclassified(grace_hours=24)
        self.session.commit()
        self.assertEqual(deleted, 2)

        # Verify BAD1 and BADETF are gone
        self.assertIsNone(comp_repo.get_by_ticker("BAD1"))
        self.assertIsNone(comp_repo.get_by_ticker("BADETF"))

        # Verify GOOD, BAD2 (under grace), and SCHD (valid ETF) still exist
        self.assertIsNotNone(comp_repo.get_by_ticker("GOOD"))
        self.assertIsNotNone(comp_repo.get_by_ticker("BAD2"))
        self.assertIsNotNone(comp_repo.get_by_ticker("SCHD"))

    def test_ticker_search_relevance_ranking_and_base_ticker_lookup(self) -> None:
        comp_repo = CompanyRepository(self.session)
        exch_ams = ExchangeRepository(self.session).upsert(code="AMS", name="Euronext Amsterdam")
        exch_nyse = ExchangeRepository(self.session).upsert(code="NYSE", name="New York Stock Exchange")
        self.session.commit()

        c_ahold = Company(ticker="AD.AS", name="Koninklijke Ahold Delhaize N.V.", exchange_id=exch_ams.id, sector="Consumer Defensive", is_active=True)
        c_adp = Company(ticker="ADP", name="Automatic Data Processing", exchange_id=exch_nyse.id, sector="Technology", is_active=True)
        c_broadcom = Company(ticker="AVGO", name="Broadcom Inc.", exchange_id=exch_nyse.id, sector="Technology", is_active=True)
        self.session.add_all([c_ahold, c_adp, c_broadcom])
        self.session.commit()

        # 1. get_by_ticker("AD") should resolve to AD.AS
        found = comp_repo.get_by_ticker("AD")
        self.assertIsNotNone(found)
        self.assertEqual(found.ticker, "AD.AS")

        # 2. list_companies(search="AD") should rank AD.AS first, ADP second, Broadcom third
        results = comp_repo.list_companies(search="AD")
        self.assertGreaterEqual(len(results), 3)
        self.assertEqual(results[0].ticker, "AD.AS")
        self.assertEqual(results[1].ticker, "ADP")
        self.assertEqual(results[2].ticker, "AVGO")

    def test_max_price_filter_and_price_sorting(self) -> None:
        comp_repo = CompanyRepository(self.session)
        price_repo = PriceRepository(self.session)
        exch = ExchangeRepository(self.session).upsert(code="TEST", name="Test Exchange")
        self.session.commit()

        c_cheap = Company(ticker="CHEAP", name="Cheap Stock", exchange_id=exch.id, is_active=True)
        c_mid = Company(ticker="MID", name="Mid Stock", exchange_id=exch.id, is_active=True)
        c_exp = Company(ticker="EXP", name="Expensive Stock", exchange_id=exch.id, is_active=True)
        self.session.add_all([c_cheap, c_mid, c_exp])
        self.session.commit()

        price_repo.upsert_price(company_id=c_cheap.id, price_date=date(2026, 10, 1), close_price=8.50)
        price_repo.upsert_price(company_id=c_mid.id, price_date=date(2026, 10, 1), close_price=24.00)
        price_repo.upsert_price(company_id=c_exp.id, price_date=date(2026, 10, 1), close_price=150.00)
        self.session.commit()

        # max_price = 10 -> only cheap
        under_10 = comp_repo.list_companies(max_price=10.0)
        self.assertEqual([c.ticker for c in under_10], ["CHEAP"])
        self.assertEqual(comp_repo.count_companies(max_price=10.0), 1)

        # max_price = 25 -> cheap and mid
        under_25 = comp_repo.list_companies(max_price=25.0, sort_by="price_asc")
        self.assertEqual([c.ticker for c in under_25], ["CHEAP", "MID"])
        self.assertEqual(comp_repo.count_companies(max_price=25.0), 2)

        # sort_by = price_desc
        desc_res = comp_repo.list_companies(sort_by="price_desc")
        self.assertEqual([c.ticker for c in desc_res[:3]], ["EXP", "MID", "CHEAP"])


if __name__ == "__main__":
    unittest.main()

"""Seed script for Dividend Explorer demo data.

Populates SQLite with sample companies, dividend events, prices, and metrics
so the UI and REST API can be explored immediately without waiting for sync.
"""

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from app.analytics.calculations import calculate_dividend_metrics
from app.db.models import CompanyRelationship
from app.db.repositories import (
    CompanyRepository,
    DividendRepository,
    ExchangeRepository,
    FinancialRepository,
    PriceRepository,
)
from app.db.session import SessionLocal, init_db

DEMO_STOCKS = [
    {
        "ticker": "JNJ",
        "name": "Johnson & Johnson",
        "exchange_code": "NYSE",
        "sector": "Healthcare",
        "industry": "Drug Manufacturers - General",
        "market_cap": 375_000_000_000,
        "base_dividend": 1.19,
        "base_price": 155.0,
        "pe": 15.8,
        "fcf": 18_000_000_000,
    },
    {
        "ticker": "PG",
        "name": "Procter & Gamble Co.",
        "exchange_code": "NYSE",
        "sector": "Consumer Defensive",
        "industry": "Household & Personal Products",
        "market_cap": 380_000_000_000,
        "base_dividend": 1.0065,
        "base_price": 162.0,
        "pe": 24.2,
        "fcf": 16_500_000_000,
    },
    {
        "ticker": "KO",
        "name": "Coca-Cola Co.",
        "exchange_code": "NYSE",
        "sector": "Consumer Defensive",
        "industry": "Beverages - Non-Alcoholic",
        "market_cap": 270_000_000_000,
        "base_dividend": 0.485,
        "base_price": 63.5,
        "pe": 23.5,
        "fcf": 10_200_000_000,
    },
    {
        "ticker": "PEP",
        "name": "PepsiCo, Inc.",
        "exchange_code": "NASDAQ",
        "sector": "Consumer Defensive",
        "industry": "Beverages - Non-Alcoholic",
        "market_cap": 235_000_000_000,
        "base_dividend": 1.355,
        "base_price": 172.0,
        "pe": 22.8,
        "fcf": 9_100_000_000,
    },
    {
        "ticker": "MSFT",
        "name": "Microsoft Corporation",
        "exchange_code": "NASDAQ",
        "sector": "Technology",
        "industry": "Software - Infrastructure",
        "market_cap": 3_100_000_000_000,
        "base_dividend": 0.75,
        "base_price": 420.0,
        "pe": 35.4,
        "fcf": 67_000_000_000,
    },
    {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "exchange_code": "NASDAQ",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "market_cap": 3_400_000_000_000,
        "base_dividend": 0.25,
        "base_price": 225.0,
        "pe": 33.1,
        "fcf": 99_000_000_000,
    },
    {
        "ticker": "SCHD",
        "name": "Schwab U.S. Dividend Equity ETF",
        "exchange_code": "ARCA",
        "sector": "Financial Services",
        "industry": "Exchange Traded Fund",
        "market_cap": 58_000_000_000,
        "base_dividend": 0.70,
        "base_price": 82.5,
        "pe": None,
        "fcf": None,
        "asset_type": "ETF",
    },
]


def seed() -> None:
    print("Initializing SQLite database tables...")
    init_db()

    session = SessionLocal()
    try:
        ex_repo = ExchangeRepository(session)
        comp_repo = CompanyRepository(session)
        div_repo = DividendRepository(session)
        price_repo = PriceRepository(session)
        fin_repo = FinancialRepository(session)

        # 1. Exchanges
        nyse = ex_repo.get_or_create(code="NYSE", name="New York Stock Exchange", country="USA", currency="USD")
        nasdaq = ex_repo.get_or_create(code="NASDAQ", name="Nasdaq Stock Market", country="USA", currency="USD")
        arca = ex_repo.get_or_create(code="ARCA", name="NYSE Arca (ETFs)", country="USA", timezone="America/New_York", currency="USD")
        ams = ex_repo.get_or_create(code="AMS", name="Euronext Amsterdam", country="Netherlands", timezone="Europe/Amsterdam", currency="EUR")
        par = ex_repo.get_or_create(code="PAR", name="Euronext Paris", country="France", timezone="Europe/Paris", currency="EUR")
        fra = ex_repo.get_or_create(code="FRA", name="XETRA / Frankfurt", country="Germany", timezone="Europe/Berlin", currency="EUR")
        bit = ex_repo.get_or_create(code="BIT", name="Borsa Italiana", country="Italy", timezone="Europe/Rome", currency="EUR")
        lse = ex_repo.get_or_create(code="LSE", name="London Stock Exchange", country="UK", timezone="Europe/London", currency="GBP")
        ex_map = {"NYSE": nyse, "NASDAQ": nasdaq, "ARCA": arca, "AMS": ams, "PAR": par, "FRA": fra, "BIT": bit, "LSE": lse}
        session.commit()

        today = date.today()

        created_companies = []

        # 2. Companies & Data
        for item in DEMO_STOCKS:
            exchange = ex_map[item["exchange_code"]]
            company, _ = comp_repo.upsert(
                ticker=item["ticker"],
                exchange_id=exchange.id,
                name=item["name"],
                sector=item["sector"],
                industry=item["industry"],
                currency="USD",
                country="USA",
                asset_type=item.get("asset_type", "STOCK"),
            )
            created_companies.append(company)

            # Dividends: 8 quarterly events back in time
            events = []
            base_div = item["base_dividend"]
            for i in range(8):
                # quarterly: ~91 days apart
                event_date = today - timedelta(days=91 * i + 15)
                # simulate slight annual growth
                payout = round(base_div * (0.95 ** (i // 4)), 4)
                ev, _ = div_repo.upsert_event(
                    company_id=company.id,
                    ex_date=event_date,
                    pay_date=event_date + timedelta(days=21),
                    amount=payout,
                    currency="USD",
                    status="ACTUAL",
                )
                events.append(ev)

            # Prices: 30 days of daily close prices
            base_p = item["base_price"]
            for d in range(30):
                p_date = today - timedelta(days=d)
                # Skip weekends
                if p_date.weekday() >= 5:
                    continue
                var = ((d % 5) - 2) * 0.4
                p = round(base_p + var, 2)
                price_repo.upsert_price(
                    company_id=company.id,
                    price_date=p_date,
                    open_price=round(p * 0.995, 2),
                    high_price=round(p * 1.008, 2),
                    low_price=round(p * 0.991, 2),
                    close_price=p,
                    volume=10_000_000,
                )

            # Financials
            fin_repo.upsert_metric(
                company_id=company.id,
                market_cap=item["market_cap"],
                pe_ratio=item["pe"],
                price_to_book=round(item["pe"] * 0.25, 2) if item["pe"] is not None else None,
                operating_cash_flow=round(item["fcf"] * 1.2, 2) if item["fcf"] is not None else None,
                free_cash_flow=item["fcf"],
            )

            # Calculate Analytics
            db_events = div_repo.list_by_company(company.id)
            latest_price = price_repo.get_latest_price(company.id)
            fin_metric = fin_repo.get_metric(company.id)

            close_p = latest_price.close if latest_price else base_p

            calc = calculate_dividend_metrics(
                events=db_events,
                latest_price=close_p,
                financial=fin_metric,
            )

            div_repo.upsert_metric(
                company_id=company.id,
                **asdict(calc),
            )

        # 3. Add explicit competitor relationships
        # KO <-> PEP
        c_map = {c.ticker: c for c in created_companies}
        if "KO" in c_map and "PEP" in c_map:
            ko = c_map["KO"]
            pep = c_map["PEP"]
            # Check if relationship exists
            existing = (
                session.query(CompanyRelationship)
                .filter(
                    CompanyRelationship.company_id == ko.id,
                    CompanyRelationship.related_company_id == pep.id,
                )
                .first()
            )
            if not existing:
                session.add(
                    CompanyRelationship(
                        company_id=ko.id,
                        related_company_id=pep.id,
                        relationship_type="competitor",
                        score=0.95,
                    )
                )
                session.add(
                    CompanyRelationship(
                        company_id=pep.id,
                        related_company_id=ko.id,
                        relationship_type="competitor",
                        score=0.95,
                    )
                )

        session.commit()
        print(f"Successfully seeded {len(DEMO_STOCKS)} companies and relationships into SQLite.")
    finally:
        session.close()


if __name__ == "__main__":
    seed()

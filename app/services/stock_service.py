from datetime import date
from typing import Any, Optional, Sequence
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Company, CompanyRelationship, DividendEvent, DividendMetric, Exchange, FinancialMetric
from app.db.repositories import (
    CompanyRepository,
    DividendRepository,
    ExchangeRepository,
    FinancialRepository,
    PriceRepository,
)


class StockService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.exchange_repo = ExchangeRepository(session)
        self.company_repo = CompanyRepository(session)
        self.dividend_repo = DividendRepository(session)
        self.price_repo = PriceRepository(session)
        self.financial_repo = FinancialRepository(session)

    def list_exchanges(self, active_only: bool = True) -> Sequence[Exchange]:
        return self.exchange_repo.list_all(active_only=active_only)

    def get_exchange_by_code(self, code: str) -> Optional[Exchange]:
        return self.exchange_repo.get_by_code(code)

    def list_companies(
        self,
        exchange_code: Optional[str] = None,
        sector: Optional[str] = None,
        industry: Optional[str] = None,
        search: Optional[str] = None,
        asset_type: Optional[str] = None,
        is_active: Optional[bool] = True,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Company]:
        exchange_id = None
        if exchange_code:
            exchange = self.exchange_repo.get_by_code(exchange_code)
            if not exchange:
                return []
            exchange_id = exchange.id

        return self.company_repo.list_companies(
            exchange_id=exchange_id,
            sector=sector,
            industry=industry,
            search=search,
            asset_type=asset_type,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

    def count_companies(
        self,
        exchange_code: Optional[str] = None,
        sector: Optional[str] = None,
        industry: Optional[str] = None,
        search: Optional[str] = None,
        asset_type: Optional[str] = None,
        is_active: Optional[bool] = True,
    ) -> int:
        exchange_id = None
        if exchange_code:
            exchange = self.exchange_repo.get_by_code(exchange_code)
            if not exchange:
                return 0
            exchange_id = exchange.id

        return self.company_repo.count_companies(
            exchange_id=exchange_id,
            sector=sector,
            industry=industry,
            search=search,
            asset_type=asset_type,
            is_active=is_active,
        )

    def get_company_by_ticker(self, ticker: str) -> Optional[Company]:
        return self.company_repo.get_by_ticker(ticker)

    def get_company_detail(self, ticker: str) -> Optional[dict[str, Any]]:
        stmt = (
            select(Company)
            .where(Company.ticker == ticker.upper())
            .options(
                joinedload(Company.exchange),
                joinedload(Company.dividend_metric),
                joinedload(Company.financial_metric),
            )
        )
        company = self.session.execute(stmt).scalars().first()
        if not company:
            return None

        latest_dividend = self.dividend_repo.get_latest_event(company.id)
        latest_price = self.price_repo.get_latest_price(company.id)
        dividends = self.dividend_repo.list_by_company(company.id, limit=20)
        recent_prices = self.price_repo.get_history(company.id, limit=30)

        return {
            "company": company,
            "exchange": company.exchange,
            "dividend_metric": company.dividend_metric,
            "metric": company.dividend_metric,
            "financial_metric": company.financial_metric,
            "financial": company.financial_metric,
            "latest_dividend": latest_dividend,
            "dividends": dividends,
            "dividend_history": dividends,
            "latest_price": latest_price,
            "recent_prices": recent_prices,
            "prices": recent_prices,
        }

    get_company_details = get_company_detail

    def search_companies(
        self,
        query: Optional[str] = None,
        sector: Optional[str] = None,
        industry: Optional[str] = None,
        asset_type: Optional[str] = None,
        sort_by: Optional[str] = "ticker",
        page: int = 1,
        page_size: int = 30,
    ) -> dict[str, Any]:
        offset = max(0, (page - 1) * page_size)
        total = self.count_companies(
            sector=sector,
            industry=industry,
            search=query,
            asset_type=asset_type,
            is_active=True,
        )
        items = self.list_companies(
            sector=sector,
            industry=industry,
            search=query,
            asset_type=asset_type,
            is_active=True,
            limit=page_size,
            offset=offset,
        )
        pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 1
        return {
            "items": items,
            "total": total,
            "page": page,
            "pages": pages,
        }

    def list_sectors(self) -> Sequence[str]:
        return self.company_repo.list_sectors()

    get_available_sectors = list_sectors

    def list_industries(self, sector: Optional[str] = None) -> Sequence[str]:
        return self.company_repo.list_industries(sector=sector)

    def get_competitors(self, ticker: str, limit: int = 5) -> Sequence[Company]:
        company = self.company_repo.get_by_ticker(ticker)
        if not company:
            return []
        stmt = (
            select(Company)
            .join(CompanyRelationship, CompanyRelationship.related_company_id == Company.id)
            .where(CompanyRelationship.company_id == company.id)
            .order_by(desc(CompanyRelationship.score))
            .limit(limit)
        )
        relationships = self.session.execute(stmt).scalars().all()
        if relationships:
            return relationships

        # ponytail: dynamic fallback to peers in same industry/sector; ceiling is simple industry match, upgrade to GICS sub-industry embedding if precision clustering needed
        if company.industry:
            stmt = (
                select(Company)
                .where(Company.industry == company.industry, Company.id != company.id)
                .limit(limit)
            )
            peers = self.session.execute(stmt).scalars().all()
            if peers:
                return peers

        if company.sector:
            stmt = (
                select(Company)
                .where(Company.sector == company.sector, Company.id != company.id)
                .limit(limit)
            )
            return self.session.execute(stmt).scalars().all()

        return []

    def get_competitor_comparison(self, ticker: str, limit: int = 5) -> Optional[dict[str, Any]]:
        target = self.company_repo.get_by_ticker(ticker)
        if not target:
            return None

        peers = self.get_competitors(ticker, limit=limit)
        all_companies = [target] + list(peers)
        company_ids = [c.id for c in all_companies]

        stmt = select(DividendMetric).where(DividendMetric.company_id.in_(company_ids))
        metrics_by_id = {m.company_id: m for m in self.session.execute(stmt).scalars().all()}

        stmt = select(FinancialMetric).where(FinancialMetric.company_id.in_(company_ids))
        fin_by_id = {f.company_id: f for f in self.session.execute(stmt).scalars().all()}

        def _make_peer_dict(comp: Company) -> dict[str, Any]:
            m = metrics_by_id.get(comp.id)
            f = fin_by_id.get(comp.id)
            return {
                "ticker": comp.ticker,
                "name": comp.name,
                "current_yield": m.current_yield if m else None,
                "payout_ratio": m.payout_ratio if m else None,
                "growth_3y": m.growth_3y if m else None,
                "quality_score": m.quality_score if m else None,
                "pe_ratio": f.pe_ratio if f else None,
            }

        target_dict = _make_peer_dict(target)
        peer_dicts = [_make_peer_dict(p) for p in peers]

        # Calculate industry medians/averages
        industry_yields = [p["current_yield"] for p in peer_dicts if p["current_yield"] is not None]
        if target_dict["current_yield"] is not None:
            industry_yields.append(target_dict["current_yield"])
        avg_yield = round(sum(industry_yields) / len(industry_yields), 4) if industry_yields else None

        industry_scores = [p["quality_score"] for p in peer_dicts if p["quality_score"] is not None]
        if target_dict["quality_score"] is not None:
            industry_scores.append(target_dict["quality_score"])
        avg_quality = round(sum(industry_scores) / len(industry_scores), 1) if industry_scores else None

        return {
            "target": target_dict,
            "peers": peer_dicts,
            "industry": target.industry,
            "sector": target.sector,
            "industry_avg_yield": avg_yield,
            "industry_avg_quality": avg_quality,
        }

    def get_top_yields(self, limit: int = 20) -> Sequence[tuple[Company, DividendMetric]]:
        stmt = (
            select(Company, DividendMetric)
            .join(DividendMetric, DividendMetric.company_id == Company.id)
            .where(DividendMetric.current_yield.is_not(None), DividendMetric.current_yield > 0)
            .order_by(desc(DividendMetric.current_yield))
            .limit(limit)
        )
        return self.session.execute(stmt).all()

    def get_dividend_growth_leaders(self, limit: int = 20) -> Sequence[tuple[Company, DividendMetric]]:
        stmt = (
            select(Company, DividendMetric)
            .join(DividendMetric, DividendMetric.company_id == Company.id)
            .where(DividendMetric.growth_3y.is_not(None), DividendMetric.growth_3y > 0)
            .order_by(desc(DividendMetric.growth_3y))
            .limit(limit)
        )
        return self.session.execute(stmt).all()

    def get_quality_leaders(self, limit: int = 20) -> Sequence[tuple[Company, DividendMetric]]:
        stmt = (
            select(Company, DividendMetric)
            .join(DividendMetric, DividendMetric.company_id == Company.id)
            .where(DividendMetric.quality_score.is_not(None))
            .order_by(desc(DividendMetric.quality_score))
            .limit(limit)
        )
        return self.session.execute(stmt).all()

    def get_dividend_calendar(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        days: Optional[int] = None,
        limit: int = 50,
    ) -> Sequence[tuple[DividendEvent, Company]]:
        base_stmt = (
            select(DividendEvent, Company)
            .join(Company, DividendEvent.company_id == Company.id)
        )
        stmt = base_stmt
        if start_date:
            stmt = stmt.where(DividendEvent.ex_date >= start_date)
        if end_date:
            stmt = stmt.where(DividendEvent.ex_date <= end_date)
        elif days and not start_date:
            from datetime import timedelta
            window_start = date.today() - timedelta(days=30)
            window_end = date.today() + timedelta(days=days)
            window_stmt = stmt.where(DividendEvent.ex_date >= window_start, DividendEvent.ex_date <= window_end)
            res = self.session.execute(window_stmt.order_by(desc(DividendEvent.ex_date)).limit(limit)).all()
            if res:
                return res
            # Fallback if no events in current window (e.g. historical data or testing)
            stmt = base_stmt
        stmt = stmt.order_by(desc(DividendEvent.ex_date)).limit(limit)
        return self.session.execute(stmt).all()

    def get_industry_summaries(self) -> list[dict[str, Any]]:
        # Retrieve all active companies with metrics
        stmt = (
            select(Company, DividendMetric)
            .outerjoin(DividendMetric, DividendMetric.company_id == Company.id)
            .where(Company.is_active == True, Company.industry.is_not(None))
        )
        rows = self.session.execute(stmt).all()
        by_industry: dict[tuple[str, str], list[tuple[Company, Optional[DividendMetric]]]] = {}
        for comp, metric in rows:
            key = (comp.sector or "Unclassified", comp.industry or "Unclassified")
            by_industry.setdefault(key, []).append((comp, metric))

        summaries = []
        for (sector, industry), group in sorted(by_industry.items()):
            yields = [m.current_yield for _, m in group if m and m.current_yield is not None]
            scores = [m.quality_score for _, m in group if m and m.quality_score is not None]

            avg_yield = round(sum(yields) / len(yields), 4) if yields else None
            median_yield = None
            if yields:
                sorted_y = sorted(yields)
                mid = len(sorted_y) // 2
                median_yield = sorted_y[mid] if len(sorted_y) % 2 != 0 else round((sorted_y[mid - 1] + sorted_y[mid]) / 2, 4)

            avg_score = round(sum(scores) / len(scores), 1) if scores else None
            top_tickers = [c.ticker for c, _ in group[:5]]

            summaries.append({
                "sector": sector,
                "industry": industry,
                "company_count": len(group),
                "avg_yield": avg_yield,
                "avg_dividend_yield": avg_yield,
                "median_yield": median_yield,
                "median_dividend_yield": median_yield,
                "avg_quality_score": avg_score,
                "top_tickers": top_tickers,
            })
        return summaries

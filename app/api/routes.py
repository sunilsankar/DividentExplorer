"""FastAPI router for all /api/v1 read-only REST endpoints."""

import math
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    CompanyDetailOut,
    CompanySummaryOut,
    CompetitorComparisonOut,
    DataChangeOut,
    DividendEventOut,
    DividendMetricOut,
    DividendMetricSummary,
    ExchangeOut,
    FinancialMetricOut,
    IndustrySummaryOut,
    PaginatedResponse,
    PriceHistoryOut,
    PriceSummary,
    SyncJobOut,
    SyncRunOut,
    SyncStatusOverviewOut,
    WorkerStatusOut,
)
from app.db.models import Company, DataChange, DividendEvent, DividendMetric, Exchange, FinancialMetric, PriceHistory, SyncJob, SyncRun, WorkerStatus, utcnow
from app.db.repositories import ChangeRepository, DividendRepository, FinancialRepository, PriceRepository
from app.db.session import get_db
from app.services.stock_service import StockService
from app.sync.queue import SyncQueue

router = APIRouter(prefix="/api/v1")


# ---------------------------------------------------------------------------
# Exchanges
# ---------------------------------------------------------------------------
@router.get("/exchanges", response_model=list[ExchangeOut], tags=["Exchanges"])
def list_exchanges(
    active_only: bool = Query(True, description="Filter for active exchanges only"),
    db: Session = Depends(get_db),
) -> list[ExchangeOut]:
    service = StockService(db)
    exchanges = service.list_exchanges(active_only=active_only)
    return [ExchangeOut.model_validate(e) for e in exchanges]


@router.get("/exchanges/{code}", response_model=ExchangeOut, tags=["Exchanges"])
def get_exchange(code: str, db: Session = Depends(get_db)) -> ExchangeOut:
    service = StockService(db)
    exchange = service.get_exchange_by_code(code.upper())
    if not exchange:
        raise HTTPException(status_code=404, detail=f"Exchange '{code.upper()}' not found")
    return ExchangeOut.model_validate(exchange)


# ---------------------------------------------------------------------------
# Companies / Stocks
# ---------------------------------------------------------------------------
@router.get("/companies", response_model=PaginatedResponse[CompanySummaryOut], tags=["Companies"])
def list_companies(
    exchange: Optional[str] = Query(None, description="Filter by exchange code (e.g. NYSE, NASDAQ)"),
    sector: Optional[str] = Query(None, description="Filter by sector"),
    industry: Optional[str] = Query(None, description="Filter by industry"),
    asset_type: Optional[str] = Query(None, description="Filter by asset type (e.g. STOCK, ETF)"),
    search: Optional[str] = Query(None, description="Search ticker or company name"),
    is_active: Optional[bool] = Query(True, description="Filter active status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    db: Session = Depends(get_db),
) -> PaginatedResponse[CompanySummaryOut]:
    service = StockService(db)
    offset = (page - 1) * page_size
    companies = service.list_companies(
        exchange_code=exchange,
        sector=sector,
        industry=industry,
        search=search,
        asset_type=asset_type,
        is_active=is_active,
        limit=page_size,
        offset=offset,
    )
    total = service.count_companies(
        exchange_code=exchange,
        sector=sector,
        industry=industry,
        search=search,
        asset_type=asset_type,
        is_active=is_active,
    )
    pages = math.ceil(total / page_size) if page_size else 1

    items: list[CompanySummaryOut] = []
    for c in companies:
        c_dict = {
            "id": c.id,
            "ticker": c.ticker,
            "name": c.name,
            "exchange_code": c.exchange.code if c.exchange else "",
            "sector": c.sector,
            "industry": c.industry,
            "country": c.country,
            "currency": c.currency,
            "asset_type": getattr(c, "asset_type", "STOCK") or "STOCK",
            "is_active": c.is_active,
            "current_yield": c.dividend_metric.current_yield if c.dividend_metric else None,
            "quality_score": c.dividend_metric.quality_score if c.dividend_metric else None,
        }
        items.append(CompanySummaryOut(**c_dict))

    return PaginatedResponse[CompanySummaryOut](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/companies/{ticker}", response_model=CompanyDetailOut, tags=["Companies"])
def get_company(ticker: str, db: Session = Depends(get_db)) -> CompanyDetailOut:
    service = StockService(db)
    detail = service.get_company_detail(ticker.upper())
    if not detail:
        raise HTTPException(status_code=404, detail=f"Company '{ticker.upper()}' not found")

    company = detail["company"]
    metric = detail["dividend_metric"]
    price = detail["latest_price"]

    div_summary = None
    if metric:
        div_summary = DividendMetricSummary.model_validate(metric)

    price_summary = None
    if price:
        price_summary = PriceSummary(
            date=price.date,
            close=price.close,
            adj_close=price.adj_close,
            volume=price.volume,
        )

    return CompanyDetailOut(
        id=company.id,
        ticker=company.ticker,
        name=company.name,
        exchange_code=detail["exchange"].code if detail["exchange"] else "",
        sector=company.sector,
        industry=company.industry,
        country=company.country,
        currency=company.currency,
        is_active=company.is_active,
        created_at=company.created_at,
        updated_at=company.updated_at,
        dividend_metric=div_summary,
        latest_price=price_summary,
    )


# ---------------------------------------------------------------------------
# Dividends & Metrics
# ---------------------------------------------------------------------------
@router.get("/dividends", response_model=PaginatedResponse[DividendEventOut], tags=["Dividends"])
def list_dividends(
    ticker: Optional[str] = Query(None, description="Filter by ticker"),
    start_date: Optional[date] = Query(None, description="Start ex-dividend date"),
    end_date: Optional[date] = Query(None, description="End ex-dividend date"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    db: Session = Depends(get_db),
) -> PaginatedResponse[DividendEventOut]:
    service = StockService(db)
    stmt = select(DividendEvent).join(Company, DividendEvent.company_id == Company.id)
    count_stmt = select(func.count(DividendEvent.id)).join(Company, DividendEvent.company_id == Company.id)

    if ticker:
        stmt = stmt.where(Company.ticker == ticker.upper())
        count_stmt = count_stmt.where(Company.ticker == ticker.upper())
    if start_date:
        stmt = stmt.where(DividendEvent.ex_date >= start_date)
        count_stmt = count_stmt.where(DividendEvent.ex_date >= start_date)
    if end_date:
        stmt = stmt.where(DividendEvent.ex_date <= end_date)
        count_stmt = count_stmt.where(DividendEvent.ex_date <= end_date)

    total = db.execute(count_stmt).scalar_one()
    offset = (page - 1) * page_size
    stmt = stmt.order_by(desc(DividendEvent.ex_date)).limit(page_size).offset(offset)
    events = db.execute(stmt).scalars().all()
    pages = math.ceil(total / page_size) if page_size else 1

    return PaginatedResponse[DividendEventOut](
        items=[DividendEventOut.model_validate(e) for e in events],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/dividend-metrics/{ticker}", response_model=DividendMetricOut, tags=["Dividends"])
def get_dividend_metrics(ticker: str, db: Session = Depends(get_db)) -> DividendMetricOut:
    service = StockService(db)
    company = service.get_company_by_ticker(ticker.upper())
    if not company:
        raise HTTPException(status_code=404, detail=f"Company '{ticker.upper()}' not found")

    metric = DividendRepository(db).get_metric(company.id)
    if not metric:
        raise HTTPException(status_code=404, detail=f"No dividend metrics found for '{ticker.upper()}'")
    return DividendMetricOut.model_validate(metric)


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
@router.get("/prices/{ticker}", response_model=list[PriceHistoryOut], tags=["Prices"])
def get_price_history(
    ticker: str,
    start_date: Optional[date] = Query(None, description="Start date"),
    end_date: Optional[date] = Query(None, description="End date"),
    limit: int = Query(365, ge=1, le=1000, description="Max records to return"),
    db: Session = Depends(get_db),
) -> list[PriceHistoryOut]:
    service = StockService(db)
    company = service.get_company_by_ticker(ticker.upper())
    if not company:
        raise HTTPException(status_code=404, detail=f"Company '{ticker.upper()}' not found")

    prices = PriceRepository(db).get_history(company.id, start_date=start_date, end_date=end_date, limit=limit)
    return [PriceHistoryOut.model_validate(p) for p in prices]


# ---------------------------------------------------------------------------
# Financials
# ---------------------------------------------------------------------------
@router.get("/financials/{ticker}", response_model=FinancialMetricOut, tags=["Financials"])
def get_financials(ticker: str, db: Session = Depends(get_db)) -> FinancialMetricOut:
    service = StockService(db)
    company = service.get_company_by_ticker(ticker.upper())
    if not company:
        raise HTTPException(status_code=404, detail=f"Company '{ticker.upper()}' not found")

    financial = FinancialRepository(db).get_metric(company.id)
    if not financial:
        raise HTTPException(status_code=404, detail=f"No financial metrics found for '{ticker.upper()}'")
    return FinancialMetricOut.model_validate(financial)


# ---------------------------------------------------------------------------
# Industries
# ---------------------------------------------------------------------------
@router.get("/industries", response_model=list[IndustrySummaryOut], tags=["Industries"])
def list_industries(db: Session = Depends(get_db)) -> list[IndustrySummaryOut]:
    service = StockService(db)
    summaries = service.get_industry_summaries()
    return [IndustrySummaryOut(**s) for s in summaries]


# ---------------------------------------------------------------------------
# Competitors
# ---------------------------------------------------------------------------
@router.get("/competitors/{ticker}", response_model=CompetitorComparisonOut, tags=["Competitors"])
def get_competitor_comparison(ticker: str, db: Session = Depends(get_db)) -> CompetitorComparisonOut:
    service = StockService(db)
    comparison = service.get_competitor_comparison(ticker.upper())
    if not comparison:
        raise HTTPException(status_code=404, detail=f"Company '{ticker.upper()}' not found")
    return CompetitorComparisonOut(**comparison)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
@router.get("/analytics/top-yields", response_model=list[CompanySummaryOut], tags=["Analytics"])
def get_top_yields(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[CompanySummaryOut]:
    service = StockService(db)
    rows = service.get_top_yields(limit=limit)
    result = []
    for comp, metric in rows:
        result.append(
            CompanySummaryOut(
                id=comp.id,
                ticker=comp.ticker,
                name=comp.name,
                exchange_code=comp.exchange.code if comp.exchange else "",
                sector=comp.sector,
                industry=comp.industry,
                country=comp.country,
                currency=comp.currency,
                is_active=comp.is_active,
                current_yield=metric.current_yield if metric else None,
                quality_score=metric.quality_score if metric else None,
            )
        )
    return result


@router.get("/analytics/dividend-growth", response_model=list[CompanySummaryOut], tags=["Analytics"])
def get_dividend_growth(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[CompanySummaryOut]:
    service = StockService(db)
    rows = service.get_dividend_growth_leaders(limit=limit)
    result = []
    for comp, metric in rows:
        result.append(
            CompanySummaryOut(
                id=comp.id,
                ticker=comp.ticker,
                name=comp.name,
                exchange_code=comp.exchange.code if comp.exchange else "",
                sector=comp.sector,
                industry=comp.industry,
                country=comp.country,
                currency=comp.currency,
                is_active=comp.is_active,
                current_yield=metric.current_yield if metric else None,
                quality_score=metric.quality_score if metric else None,
            )
        )
    return result


@router.get("/analytics/quality-leaders", response_model=list[CompanySummaryOut], tags=["Analytics"])
def get_quality_leaders(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[CompanySummaryOut]:
    service = StockService(db)
    rows = service.get_quality_leaders(limit=limit)
    result = []
    for comp, metric in rows:
        result.append(
            CompanySummaryOut(
                id=comp.id,
                ticker=comp.ticker,
                name=comp.name,
                exchange_code=comp.exchange.code if comp.exchange else "",
                sector=comp.sector,
                industry=comp.industry,
                country=comp.country,
                currency=comp.currency,
                is_active=comp.is_active,
                current_yield=metric.current_yield if metric else None,
                quality_score=metric.quality_score if metric else None,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Sync Status & Queue
# ---------------------------------------------------------------------------
@router.get("/sync/status", response_model=SyncStatusOverviewOut, tags=["Synchronization"])
def get_sync_status(db: Session = Depends(get_db)) -> SyncStatusOverviewOut:
    queue = SyncQueue()
    stats = queue.get_stats(db)

    # Active workers in last 5 minutes
    worker_stmt = select(WorkerStatus).order_by(desc(WorkerStatus.heartbeat_at)).limit(10)
    workers = db.execute(worker_stmt).scalars().all()

    # Recent runs
    run_stmt = select(SyncRun).order_by(desc(SyncRun.started_at)).limit(10)
    runs = db.execute(run_stmt).scalars().all()

    return SyncStatusOverviewOut(
        workers=[WorkerStatusOut.model_validate(w) for w in workers],
        queue_stats=stats,
        recent_runs=[SyncRunOut.model_validate(r) for r in runs],
    )


@router.get("/sync/jobs", response_model=PaginatedResponse[SyncJobOut], tags=["Synchronization"])
def list_sync_jobs(
    status: Optional[str] = Query(None, description="Filter by job status (PENDING, RUNNING, COMPLETED, FAILED, RETRY)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> PaginatedResponse[SyncJobOut]:
    stmt = select(SyncJob)
    count_stmt = select(func.count(SyncJob.id))

    if status:
        stmt = stmt.where(SyncJob.status == status.upper())
        count_stmt = count_stmt.where(SyncJob.status == status.upper())

    total = db.execute(count_stmt).scalar_one()
    offset = (page - 1) * page_size
    stmt = stmt.order_by(desc(SyncJob.created_at)).limit(page_size).offset(offset)
    jobs = db.execute(stmt).scalars().all()
    pages = math.ceil(total / page_size) if page_size else 1

    return PaginatedResponse[SyncJobOut](
        items=[SyncJobOut.model_validate(j) for j in jobs],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


# ---------------------------------------------------------------------------
# Change History
# ---------------------------------------------------------------------------
@router.get("/changes", response_model=list[DataChangeOut], tags=["Changes"])
def list_changes(
    limit: int = Query(50, ge=1, le=200),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    entity_id: Optional[int] = Query(None, description="Filter by entity id"),
    db: Session = Depends(get_db),
) -> list[DataChangeOut]:
    repo = ChangeRepository(db)
    changes = repo.list_recent(limit=limit, entity_type=entity_type, entity_id=entity_id)
    return [DataChangeOut.model_validate(c) for c in changes]

"""Web UI routes using Jinja2 and HTMX."""

from pathlib import Path
from typing import Any, Optional
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import SyncJob, utcnow
from app.db.repositories import (
    ChangeRepository,
    CompanyRepository,
    DividendRepository,
    ExchangeRepository,
    FinancialRepository,
    PriceRepository,
)
from app.db.session import get_db
from app.services.stock_service import StockService
from app.services.sync_service import SyncService
from app.sync.queue import SyncQueue, SyncRunManager, WorkerHeartbeatManager

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

CURRENCY_SYMBOLS = {"EUR": "€", "GBP": "£", "USD": "$"}


def currency_symbol(currency: Optional[str]) -> str:
    if not currency:
        return "$"
    return CURRENCY_SYMBOLS.get(currency.strip().upper(), "$")


templates.env.filters["currency_symbol"] = currency_symbol

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def dashboard_view(request: Request, db: Session = Depends(get_db)):
    stock_service = StockService(db)
    sync_service = SyncService(db)
    change_repo = ChangeRepository(db)

    total_companies = len(CompanyRepository(db).list_companies(limit=10000))
    raw_top_yields = stock_service.get_top_yields(limit=5)
    top_yields = [
        {
            "ticker": comp.ticker,
            "company_name": comp.name,
            "sector": comp.sector,
            "current_yield": metric.current_yield if metric else 0.0,
            "annual_dividend": metric.annual_dividend if metric else None,
            "dividend_quality_score": metric.quality_score if metric else None,
            "currency": comp.currency,
        }
        for comp, metric in raw_top_yields
    ]

    raw_quality_leaders = stock_service.get_quality_leaders(limit=5)
    quality_leaders = [
        {
            "ticker": comp.ticker,
            "company_name": comp.name,
            "dividend_quality_score": metric.quality_score if metric else None,
            "years_growing": metric.years_growing if metric else 0,
            "payout_ratio": metric.payout_ratio if metric else None,
            "current_yield": metric.current_yield if metric else None,
        }
        for comp, metric in raw_quality_leaders
    ]

    recent_changes = change_repo.list_recent(limit=5)
    queue_overview = sync_service.get_queue_status()

    avg_yield = 0.0
    if top_yields:
        avg_yield = sum(t["current_yield"] for t in top_yields if t.get("current_yield")) / len(top_yields)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "active_tab": "dashboard",
            "total_companies": total_companies,
            "avg_yield": avg_yield,
            "queue_pending_jobs": queue_overview.get("pending_jobs", queue_overview.get("PENDING", 0)),
            "top_yields": top_yields,
            "quality_leaders": quality_leaders,
            "recent_changes": recent_changes,
        },
    )


@router.get("/stocks", response_class=HTMLResponse)
def stocks_view(
    request: Request,
    q: Optional[str] = None,
    sector: Optional[str] = None,
    asset_type: Optional[str] = None,
    sort: Optional[str] = "ticker",
    page: int = 1,
    db: Session = Depends(get_db),
):
    stock_service = StockService(db)
    res = stock_service.search_companies(
        query=q, sector=sector, asset_type=asset_type, sort_by=sort, page=page, page_size=30
    )
    sectors = stock_service.get_available_sectors()

    return templates.TemplateResponse(
        request=request,
        name="stocks.html",
        context={
            "active_tab": "etfs" if asset_type == "ETF" else "stocks",
            "stocks": res["items"],
            "total_count": res["total"],
            "page": res["page"],
            "total_pages": res["pages"],
            "query": q,
            "selected_sector": sector,
            "selected_asset_type": asset_type,
            "sectors": sectors,
            "sort": sort,
        },
    )


@router.get("/stocks/table", response_class=HTMLResponse)
def stocks_table_partial(
    request: Request,
    q: Optional[str] = None,
    sector: Optional[str] = None,
    asset_type: Optional[str] = None,
    sort: Optional[str] = "ticker",
    page: int = 1,
    db: Session = Depends(get_db),
):
    stock_service = StockService(db)
    res = stock_service.search_companies(
        query=q, sector=sector, asset_type=asset_type, sort_by=sort, page=page, page_size=30
    )
    return templates.TemplateResponse(
        request=request,
        name="partials/stock_table.html",
        context={
            "stocks": res["items"],
            "total_count": res["total"],
            "page": res["page"],
            "total_pages": res["pages"],
            "selected_asset_type": asset_type,
        },
    )


@router.get("/stocks/{ticker}", response_class=HTMLResponse)
def stock_detail_view(ticker: str, request: Request, db: Session = Depends(get_db)):
    stock_service = StockService(db)
    details = stock_service.get_company_details(ticker)
    if not details:
        return RedirectResponse(url="/stocks", status_code=status.HTTP_302_FOUND)

    peers = stock_service.get_competitors(ticker, limit=5)

    return templates.TemplateResponse(
        request=request,
        name="stock_detail.html",
        context={
            "active_tab": "stocks",
            "company": details["company"],
            "metric": details["metric"],
            "dividends": details["dividends"],
            "latest_price": details["latest_price"],
            "prices": details["recent_prices"],
            "financial": details["financial"],
            "peers": peers,
        },
    )


@router.get("/industries", response_class=HTMLResponse)
def industries_view(request: Request, db: Session = Depends(get_db)):
    stock_service = StockService(db)
    industries = stock_service.get_industry_summaries()
    return templates.TemplateResponse(
        request=request,
        name="industries.html",
        context={
            "active_tab": "industries",
            "industries": industries,
        },
    )


@router.get("/competitors", response_class=HTMLResponse)
def competitors_view(
    request: Request, ticker: Optional[str] = None, db: Session = Depends(get_db)
):
    stock_service = StockService(db)
    comparison = None
    if ticker:
        comparison = stock_service.get_competitor_comparison(ticker, limit=5)

    return templates.TemplateResponse(
        request=request,
        name="competitors.html",
        context={
            "active_tab": "competitors",
            "target_ticker": ticker,
            "comparison": comparison,
        },
    )


@router.get("/calendar", response_class=HTMLResponse)
def calendar_view(request: Request, db: Session = Depends(get_db)):
    stock_service = StockService(db)
    raw_events = stock_service.get_dividend_calendar(days=60)
    events = [
        {
            "ex_date": ev.ex_date,
            "ticker": comp.ticker,
            "company_name": comp.name,
            "amount": ev.amount,
            "currency": ev.currency or comp.currency,
            "payment_date": ev.pay_date,
            "record_date": ev.record_date,
        }
        for ev, comp in raw_events
    ]
    return templates.TemplateResponse(
        request=request,
        name="calendar.html",
        context={
            "active_tab": "calendar",
            "events": events,
        },
    )


@router.get("/analytics", response_class=HTMLResponse)
def analytics_view(request: Request, db: Session = Depends(get_db)):
    stock_service = StockService(db)
    raw_quality_leaders = stock_service.get_quality_leaders(limit=25)
    quality_leaders = [
        {
            "ticker": comp.ticker,
            "company_name": comp.name,
            "dividend_quality_score": metric.quality_score if metric else None,
            "years_growing": metric.years_growing if metric else 0,
            "years_paying": metric.years_paying if metric else 0,
            "payout_ratio": metric.payout_ratio if metric else None,
            "current_yield": metric.current_yield if metric else None,
        }
        for comp, metric in raw_quality_leaders
    ]

    raw_growth_leaders = stock_service.get_dividend_growth_leaders(limit=25)
    growth_leaders = [
        {
            "ticker": comp.ticker,
            "company_name": comp.name,
            "growth_3y": metric.growth_3y if metric else None,
            "growth_1y": metric.growth_1y if metric else None,
            "growth_rate_3y": metric.growth_3y if metric else 0.0,
            "growth_rate_1y": metric.growth_1y if metric else None,
            "current_yield": metric.current_yield if metric else None,
            "dividend_quality_score": metric.quality_score if metric else None,
        }
        for comp, metric in raw_growth_leaders
    ]

    return templates.TemplateResponse(
        request=request,
        name="analytics.html",
        context={
            "active_tab": "analytics",
            "quality_leaders": quality_leaders,
            "growth_leaders": growth_leaders,
        },
    )


def _build_sync_context(db: Session, tab: str = "now") -> dict[str, Any]:
    sync_service = SyncService(db)
    overview = sync_service.get_queue_status()
    workers = sync_service.get_active_workers()

    now_jobs = db.execute(
        select(SyncJob)
        .where(SyncJob.status.in_(["PENDING", "RETRY", "RUNNING"]))
        .order_by(SyncJob.priority.desc(), SyncJob.next_run_at.asc(), SyncJob.id.desc())
        .limit(15)
    ).scalars().all()

    recent_jobs = db.execute(
        select(SyncJob)
        .where(SyncJob.status.in_(["COMPLETED", "FAILED", "CANCELLED"]))
        .order_by(desc(SyncJob.updated_at))
        .limit(20)
    ).scalars().all()

    stuck_running = sync_service.get_stuck_running_count(threshold_seconds=300)
    running_jobs_list = [j for j in now_jobs if j.status == "RUNNING"]

    summary = {
        "workers": len(workers),
        "worker_health": "alive" if len(workers) > 0 else "dead",
        "pending": overview.get("PENDING", 0),
        "scheduled": overview.get("RETRY", 0),
        "running": overview.get("RUNNING", 0),
        "failed_permanent": overview.get("FAILED", 0),
        "stuck_running": stuck_running,
    }

    exchanges = sync_service.get_all_exchange_progress()

    return {
        "active_tab": "sync",
        "summary": summary,
        "overview": overview,
        "workers": workers,
        "now_jobs": now_jobs,
        "recent_jobs": recent_jobs,
        "running_jobs_list": running_jobs_list,
        "recent_runs": sync_service.get_recent_runs(limit=10),
        "queue_jobs": now_jobs if tab == "now" else recent_jobs,
        "exchanges": exchanges,
        "now": utcnow(),
        "tab": tab,
    }


@router.get("/sync", response_class=HTMLResponse)
def sync_dashboard_view(request: Request, tab: str = "now", db: Session = Depends(get_db)):
    context = _build_sync_context(db, tab=tab)
    return templates.TemplateResponse(request=request, name="sync.html", context=context)


@router.get("/sync/status", response_class=HTMLResponse)
def sync_status_partial(request: Request, tab: str = "now", db: Session = Depends(get_db)):
    context = _build_sync_context(db, tab=tab)
    return templates.TemplateResponse(request=request, name="partials/sync_status.html", context=context)


@router.post("/sync/trigger", response_class=HTMLResponse)
def trigger_sync(
    request: Request,
    ticker: Optional[str] = Form(None),
    exchange: Optional[str] = Form(None),
    tab: str = "now",
    db: Session = Depends(get_db),
):
    sync_service = SyncService(db)
    if ticker:
        sync_service.enqueue_company_sync(ticker.strip().upper(), priority=9)
    elif exchange:
        sync_service.enqueue_exchange_sync(exchange.strip().upper())
    db.commit()
    return sync_status_partial(request=request, tab=tab, db=db)


@router.post("/sync/retry-failed", response_class=HTMLResponse)
def retry_failed_sync(request: Request, tab: str = "now", db: Session = Depends(get_db)):
    sync_service = SyncService(db)
    sync_service.retry_all_failed()
    db.commit()
    return sync_status_partial(request=request, tab=tab, db=db)


@router.post("/sync/reap-stuck", response_class=HTMLResponse)
def reap_stuck(request: Request, tab: str = "now", db: Session = Depends(get_db)):
    SyncQueue().reap_stale_jobs(db, stale_timeout_seconds=300)
    db.commit()
    return sync_status_partial(request=request, tab=tab, db=db)


@router.post("/sync/retry-throttled", response_class=HTMLResponse)
def retry_throttled(request: Request, tab: str = "now", db: Session = Depends(get_db)):
    stmt = select(SyncJob).where(SyncJob.status == "RETRY")
    now = utcnow()
    for j in db.execute(stmt).scalars():
        j.status = "PENDING"
        j.next_run_at = now
        j.error = None
        j.updated_at = now
    db.commit()
    return sync_status_partial(request=request, tab=tab, db=db)


@router.post("/sync/trigger-all-exchanges", response_class=HTMLResponse)
def trigger_all_exchanges(request: Request, db: Session = Depends(get_db)):
    repo = ExchangeRepository(db)
    sync_service = SyncService(db)
    for ex in repo.list_all(active_only=True):
        sync_service.enqueue_exchange_sync(ex.code)
    db.commit()
    return exchange_sync_view(request=request, db=db)


@router.get("/sync/exchanges", response_class=HTMLResponse)
def exchange_sync_view(request: Request, db: Session = Depends(get_db)):
    sync_service = SyncService(db)
    exchange_list = sync_service.get_all_exchange_progress()
    return templates.TemplateResponse(
        request=request,
        name="exchange_sync.html",
        context={
            "active_tab": "sync",
            "exchanges": exchange_list,
        },
    )


@router.get("/changes", response_class=HTMLResponse)
def changes_view(
    request: Request,
    change_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    repo = ChangeRepository(db)
    changes = repo.list_recent(limit=100, change_type=change_type)
    return templates.TemplateResponse(
        request=request,
        name="changes.html",
        context={
            "active_tab": "changes",
            "changes": changes,
            "selected_type": change_type,
        },
    )

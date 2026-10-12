"""Web UI routes using Jinja2 and HTMX."""

import calendar as pycalendar
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Company, DividendMetric, Exchange, PriceHistory, SyncJob, utcnow
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

CURRENCY_SYMBOLS = {"EUR": "€", "GBP": "£", "USD": "$", "INR": "₹"}


def currency_symbol(currency: Optional[str]) -> str:
    if not currency:
        return "$"
    return CURRENCY_SYMBOLS.get(currency.strip().upper(), "$")


templates.env.filters["currency_symbol"] = currency_symbol

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def dashboard_view(request: Request, exchange: Optional[str] = None, db: Session = Depends(get_db)):
    stock_service = StockService(db)
    sync_service = SyncService(db)
    change_repo = ChangeRepository(db)

    total_companies = len(CompanyRepository(db).list_companies(limit=10000))
    exchanges = stock_service.list_exchanges()
    selected_exchange = exchange.strip().upper() if exchange else ""
    raw_top_yields = stock_service.get_top_yields(limit=5, exchange_code=selected_exchange or None)
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
            "exchanges": exchanges,
            "selected_exchange": selected_exchange,
        },
    )


@router.get("/dashboard/top-yields", response_class=HTMLResponse)
def dashboard_top_yields_partial(request: Request, exchange: Optional[str] = None, db: Session = Depends(get_db)):
    stock_service = StockService(db)
    selected_exchange = exchange.strip().upper() if exchange else ""
    raw_top_yields = stock_service.get_top_yields(limit=5, exchange_code=selected_exchange or None)
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
    return templates.TemplateResponse(
        request=request,
        name="partials/top_yields_table.html",
        context={"top_yields": top_yields},
    )


@router.get("/india", response_class=HTMLResponse)
@router.get("/dashboard/india", response_class=HTMLResponse)
def india_dashboard_view(request: Request, exchange: Optional[str] = None, db: Session = Depends(get_db)):
    stock_service = StockService(db)
    sync_service = SyncService(db)
    comp_repo = CompanyRepository(db)

    indian_exchanges = [ex for ex in stock_service.list_exchanges() if (ex.country or "").lower() == "india" or ex.code in ("NSE", "BSE")]
    indian_exchange_codes = [ex.code for ex in indian_exchanges] or ["NSE", "BSE"]

    india_companies = [c for c in comp_repo.list_companies(limit=10000) if c.exchange and c.exchange.code in indian_exchange_codes]
    total_companies = len(india_companies)

    selected_exchange = exchange.strip().upper() if exchange else ""
    if selected_exchange and selected_exchange not in indian_exchange_codes:
        selected_exchange = ""

    raw_top_yields = stock_service.get_top_yields(
        limit=10,
        exchange_code=selected_exchange or None,
        country="India" if not selected_exchange else None,
    )
    top_yields = [
        {
            "ticker": comp.ticker,
            "company_name": comp.name,
            "sector": comp.sector,
            "current_yield": metric.current_yield if metric else 0.0,
            "annual_dividend": metric.annual_dividend if metric else None,
            "dividend_quality_score": metric.quality_score if metric else None,
            "currency": comp.currency or "INR",
        }
        for comp, metric in raw_top_yields
    ]

    raw_quality_leaders = stock_service.get_quality_leaders(
        limit=10,
        exchange_code=selected_exchange or None,
        country="India" if not selected_exchange else None,
    )
    quality_leaders = [
        {
            "ticker": comp.ticker,
            "company_name": comp.name,
            "dividend_quality_score": metric.quality_score if metric else None,
            "years_growing": metric.years_growing if metric else 0,
            "payout_ratio": metric.payout_ratio if metric else None,
            "current_yield": metric.current_yield if metric else None,
            "currency": comp.currency or "INR",
        }
        for comp, metric in raw_quality_leaders
    ]

    high_yield_count = sum(1 for t in top_yields if (t.get("current_yield") or 0.0) >= 0.06)
    avg_yield = 0.0
    if top_yields:
        avg_yield = sum(t["current_yield"] for t in top_yields if t.get("current_yield")) / len(top_yields)

    nse_progress = sync_service.get_exchange_progress("NSE")
    bse_progress = sync_service.get_exchange_progress("BSE")

    return templates.TemplateResponse(
        request=request,
        name="india_dashboard.html",
        context={
            "active_tab": "india",
            "total_companies": total_companies,
            "avg_yield": avg_yield,
            "high_yield_count": high_yield_count,
            "top_yields": top_yields,
            "quality_leaders": quality_leaders,
            "exchanges": indian_exchanges,
            "selected_exchange": selected_exchange,
            "nse_progress": nse_progress,
            "bse_progress": bse_progress,
        },
    )


@router.get("/india/top-yields", response_class=HTMLResponse)
def india_top_yields_partial(request: Request, exchange: Optional[str] = None, db: Session = Depends(get_db)):
    stock_service = StockService(db)
    selected_exchange = exchange.strip().upper() if exchange else ""
    raw_top_yields = stock_service.get_top_yields(
        limit=10,
        exchange_code=selected_exchange or None,
        country="India" if not selected_exchange else None,
    )
    top_yields = [
        {
            "ticker": comp.ticker,
            "company_name": comp.name,
            "sector": comp.sector,
            "current_yield": metric.current_yield if metric else 0.0,
            "annual_dividend": metric.annual_dividend if metric else None,
            "dividend_quality_score": metric.quality_score if metric else None,
            "currency": comp.currency or "INR",
        }
        for comp, metric in raw_top_yields
    ]
    return templates.TemplateResponse(
        request=request,
        name="partials/top_yields_table.html",
        context={"top_yields": top_yields},
    )


def _safe_float(val: Any) -> Optional[float]:
    if val is None or not str(val).strip():
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any, default: int = 1) -> int:
    if val is None or not str(val).strip():
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


@router.get("/stocks", response_class=HTMLResponse)
def stocks_view(
    request: Request,
    q: Optional[str] = None,
    sector: Optional[str] = None,
    asset_type: Optional[str] = None,
    exchange: Optional[str] = None,
    sort: Optional[str] = "ticker",
    sync_state: Optional[str] = None,
    max_price: Optional[str] = None,
    page: Optional[str] = "1",
    page_size: Optional[str] = "30",
    db: Session = Depends(get_db),
):
    real_max_price = _safe_float(max_price)
    real_page = max(1, _safe_int(page, default=1))
    real_page_size = max(1, _safe_int(page_size, default=30))

    stock_service = StockService(db)
    res = stock_service.search_companies(
        query=q,
        sector=sector,
        asset_type=asset_type,
        exchange=exchange,
        sort_by=sort,
        sync_state=sync_state,
        max_price=real_max_price,
        page=real_page,
        page_size=real_page_size,
    )
    sectors = stock_service.get_available_sectors()
    exchanges = stock_service.list_exchanges()

    return templates.TemplateResponse(
        request=request,
        name="stocks.html",
        context={
            "active_tab": "etfs" if asset_type == "ETF" else "stocks",
            "stocks": res["items"],
            "total_count": res["total"],
            "page": res["page"],
            "page_size": real_page_size,
            "total_pages": res["pages"],
            "query": q,
            "selected_sector": sector,
            "selected_asset_type": asset_type,
            "selected_exchange": exchange,
            "selected_sync_state": sync_state,
            "selected_max_price": real_max_price,
            "sectors": sectors,
            "exchanges": exchanges,
            "sort": sort,
        },
    )


@router.get("/stocks/table", response_class=HTMLResponse)
def stocks_table_partial(
    request: Request,
    q: Optional[str] = None,
    sector: Optional[str] = None,
    asset_type: Optional[str] = None,
    exchange: Optional[str] = None,
    sort: Optional[str] = "ticker",
    sync_state: Optional[str] = None,
    max_price: Optional[str] = None,
    page: Optional[str] = "1",
    page_size: Optional[str] = "30",
    db: Session = Depends(get_db),
):
    real_max_price = _safe_float(max_price)
    real_page = max(1, _safe_int(page, default=1))
    real_page_size = max(1, _safe_int(page_size, default=30))

    stock_service = StockService(db)
    res = stock_service.search_companies(
        query=q,
        sector=sector,
        asset_type=asset_type,
        exchange=exchange,
        sort_by=sort,
        sync_state=sync_state,
        max_price=real_max_price,
        page=real_page,
        page_size=real_page_size,
    )
    return templates.TemplateResponse(
        request=request,
        name="partials/stock_table.html",
        context={
            "stocks": res["items"],
            "total_count": res["total"],
            "page": res["page"],
            "page_size": real_page_size,
            "total_pages": res["pages"],
            "query": q,
            "selected_sector": sector,
            "selected_asset_type": asset_type,
            "selected_exchange": exchange,
            "selected_sync_state": sync_state,
            "selected_max_price": real_max_price,
            "sort": sort,
        },
    )


@router.get("/stocks/unclassified", response_class=HTMLResponse)
def unclassified_stocks_view(
    request: Request,
    missing: Optional[str] = None,
    page: int = 1,
    page_size: int = 30,
    db: Session = Depends(get_db),
):
    valid_missing = {"sector", "industry", "country", "currency", "multiple"}
    active_filter = missing if missing in valid_missing else None

    stock_service = StockService(db)
    companies, total, counts = stock_service.list_unclassified(
        missing_field=active_filter,
        page=page,
        page_size=page_size,
    )
    total_pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 1

    stocks_data = []
    for comp in companies:
        missing_fields = []
        if comp.asset_type != "ETF":
            if not comp.sector:
                missing_fields.append("Sector")
            if not comp.industry:
                missing_fields.append("Industry")
            if not comp.country:
                missing_fields.append("Country")
        if not comp.currency:
            missing_fields.append("Currency")

        stocks_data.append({
            "company": comp,
            "missing_fields": missing_fields,
        })

    return templates.TemplateResponse(
        request=request,
        name="unclassified.html",
        context={
            "active_tab": "stocks",
            "stocks": stocks_data,
            "total_count": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "counts": counts,
            "active_filter": active_filter or "all",
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
@router.get("/calendar/india", response_class=HTMLResponse)
def calendar_view(
    request: Request,
    year: Optional[int] = None,
    month: Optional[int] = None,
    asset_type: Optional[str] = None,
    currency: Optional[str] = None,
    exchange: Optional[str] = None,
    view: Optional[str] = "calendar",
    market: Optional[str] = None,
    db: Session = Depends(get_db),
):
    # ponytail: market toggle hardcodes india/global scope. Add markets when needed.
    selected_market = (market or "").strip().lower()
    if selected_market not in ("india", "global"):
        selected_market = "india" if request.url.path.endswith("/calendar/india") else "global"

    stock_service = StockService(db)
    available_currencies = stock_service.list_currencies(market=selected_market)
    exchanges = stock_service.list_exchanges(market=selected_market)
    normalized_asset_type = asset_type.strip().upper() if asset_type else None
    normalized_currency = currency.strip().upper() if currency else None
    normalized_exchange = exchange.strip().upper() if exchange else None

    today = date.today()
    if year is None or month is None:
        cur_year, cur_month = today.year, today.month
        days_in_cur_month = pycalendar.monthrange(cur_year, cur_month)[1]
        has_current = stock_service.get_dividend_calendar(
            asset_type=normalized_asset_type,
            currency=normalized_currency,
            exchange=normalized_exchange,
            market=selected_market,
            start_date=date(cur_year, cur_month, 1),
            end_date=date(cur_year, cur_month, days_in_cur_month),
            limit=1,
        )
        if not has_current:
            latest = stock_service.get_dividend_calendar(
                asset_type=normalized_asset_type,
                currency=normalized_currency,
                exchange=normalized_exchange,
                market=selected_market,
                limit=1,
            )
            if latest and latest[0][0].ex_date:
                cur_year, cur_month = latest[0][0].ex_date.year, latest[0][0].ex_date.month
    else:
        cur_year, cur_month = int(year), max(1, min(12, int(month)))

    prev_year, prev_month = (cur_year - 1, 12) if cur_month == 1 else (cur_year, cur_month - 1)
    next_year, next_month = (cur_year + 1, 1) if cur_month == 12 else (cur_year, cur_month + 1)

    cal_matrix = pycalendar.monthcalendar(cur_year, cur_month)
    month_name = pycalendar.month_name[cur_month]

    days_in_month = pycalendar.monthrange(cur_year, cur_month)[1]
    raw_events = stock_service.get_dividend_calendar(
        asset_type=normalized_asset_type,
        currency=normalized_currency,
        exchange=normalized_exchange,
        market=selected_market,
        start_date=date(cur_year, cur_month, 1),
        end_date=date(cur_year, cur_month, days_in_month),
        limit=500,
    )
    events = [
        {
            "ex_date": ev.ex_date,
            "ticker": comp.ticker,
            "company_name": comp.name,
            "amount": ev.amount,
            "currency": ev.currency or comp.currency,
            "payment_date": ev.pay_date,
            "record_date": ev.record_date,
            "asset_type": comp.asset_type,
            "status": ev.status,
        }
        for ev, comp in raw_events
        if ev.ex_date is not None
    ]

    events_by_day: dict[int, list[dict]] = {}
    for ev in events:
        d = ev["ex_date"]
        if d.year == cur_year and d.month == cur_month:
            events_by_day.setdefault(d.day, []).append(ev)

    context = {
        "active_tab": "calendar",
        "events": events,
        "events_by_day": events_by_day,
        "cal_matrix": cal_matrix,
        "year": cur_year,
        "month": cur_month,
        "month_name": month_name,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "selected_asset_type": normalized_asset_type or "",
        "selected_currency": normalized_currency or "",
        "selected_exchange": normalized_exchange or "",
        "available_currencies": available_currencies,
        "exchanges": exchanges,
        "current_view": view or "calendar",
        "selected_market": selected_market,
        "today_day": today.day if today.year == cur_year and today.month == cur_month else None,
    }

    if request.headers.get("HX-Request") and request.headers.get("HX-Target") == "calendar-container":
        return templates.TemplateResponse(
            request=request,
            name="partials/calendar_content.html",
            context=context,
        )

    return templates.TemplateResponse(
        request=request,
        name="calendar.html",
        context=context,
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


def _get_worker_logs(lines: int = 80) -> str:
    # ponytail: stdlib subprocess reads systemd journal without extra logging daemon; upgrade: journald socket if high frequency
    try:
        proc = subprocess.run(
            ["journalctl", "-u", "dividend-worker", "-n", str(lines), "--no-pager"],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass
    return ""


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

    log_jobs = db.execute(
        select(SyncJob)
        .order_by(desc(SyncJob.updated_at))
        .limit(50)
    ).scalars().all()

    stuck_running = sync_service.get_stuck_running_count(threshold_seconds=300)
    running_jobs_list = [j for j in now_jobs if j.status == "RUNNING"]
    raw_logs = _get_worker_logs() if tab == "logs" else ""

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
    settings = get_settings()
    unclassified_count = sync_service.count_unclassified(grace_hours=settings.auto_cleanup_grace_hours)

    return {
        "active_tab": "sync_logs" if tab == "logs" else "sync",
        "summary": summary,
        "overview": overview,
        "workers": workers,
        "now_jobs": now_jobs,
        "recent_jobs": recent_jobs,
        "log_jobs": log_jobs,
        "raw_logs": raw_logs,
        "running_jobs_list": running_jobs_list,
        "recent_runs": sync_service.get_recent_runs(limit=10),
        "queue_jobs": now_jobs if tab == "now" else (log_jobs if tab == "logs" else recent_jobs),
        "exchanges": exchanges,
        "unclassified_count": unclassified_count,
        "auto_cleanup_enabled": settings.auto_cleanup_enabled,
        "auto_cleanup_grace_hours": settings.auto_cleanup_grace_hours,
        "now": utcnow(),
        "tab": tab,
    }


@router.get("/sync", response_class=HTMLResponse)
def sync_dashboard_view(request: Request, tab: str = "now", db: Session = Depends(get_db)):
    context = _build_sync_context(db, tab=tab)
    return templates.TemplateResponse(request=request, name="sync.html", context=context)


@router.get("/sync/logs", response_class=HTMLResponse)
def sync_logs_view(request: Request, db: Session = Depends(get_db)):
    context = _build_sync_context(db, tab="logs")
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
    sync_mode: str = Form("incremental"),
    tab: str = "now",
    db: Session = Depends(get_db),
):
    sync_service = SyncService(db)
    hint: Optional[str] = None
    mode = sync_mode.strip().lower() if sync_mode else "incremental"
    if ticker:
        sync_service.enqueue_company_sync(ticker.strip().upper(), priority=9, sync_mode=mode)
    elif exchange:
        code = exchange.strip().upper()
        job, deduplicated = sync_service.enqueue_exchange_sync(code, sync_mode=mode)
        if deduplicated:
            hint = f"Exchange {code} sync is already queued/running (Job #{job.id})."
    db.commit()
    context = _build_sync_context(db, tab=tab)
    if hint:
        context["sync_dedup_hint"] = hint
    return templates.TemplateResponse(request=request, name="partials/sync_status.html", context=context)


@router.post("/sync/force", response_class=HTMLResponse)
def force_exchange_sync(
    request: Request,
    exchange: str = Form(...),
    sync_mode: str = Form("incremental"),
    db: Session = Depends(get_db),
):
    code = exchange.strip().upper()
    mode = sync_mode.strip().lower() if sync_mode else "incremental"
    sync_service = SyncService(db)
    sync_service.cancel_in_flight_exchange_syncs(code)
    sync_service.enqueue_exchange_sync(code, deduplicate=False, sync_mode=mode)
    return exchange_sync_view(request=request, db=db)


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


@router.post("/sync/cleanup-unclassified", response_class=HTMLResponse)
def cleanup_unclassified(request: Request, tab: str = "now", db: Session = Depends(get_db)):
    settings = get_settings()
    sync_service = SyncService(db)
    deleted = sync_service.cleanup_unclassified(grace_hours=settings.auto_cleanup_grace_hours)
    context = _build_sync_context(db, tab=tab)
    if deleted > 0:
        context["cleanup_notice"] = f"Removed {deleted} unclassified stock{'s' if deleted != 1 else ''}."
    else:
        context["cleanup_notice"] = "No unclassified stocks older than the grace period were found."
    return templates.TemplateResponse(request=request, name="partials/sync_status.html", context=context)


@router.post("/sync/trigger-all-exchanges", response_class=HTMLResponse)
def trigger_all_exchanges(
    request: Request,
    sync_mode: str = Form("incremental"),
    db: Session = Depends(get_db),
):
    mode = sync_mode.strip().lower() if sync_mode else "incremental"
    repo = ExchangeRepository(db)
    sync_service = SyncService(db)
    for ex in repo.list_all(active_only=True):
        sync_service.enqueue_exchange_sync(ex.code, sync_mode=mode)
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


def _safe_float(val: Optional[str], default: Optional[float] = None) -> Optional[float]:
    if not val or not val.strip():
        return default
    try:
        return float(val.strip())
    except ValueError:
        return default


@router.get("/planner", response_class=HTMLResponse)
def planner_view(
    request: Request,
    target: Optional[str] = "100",
    asset_type: Optional[str] = None,
    currency: Optional[str] = None,
    market: Optional[str] = None,
    holdings: Optional[str] = "6",
    tab: Optional[str] = "plan",
    page: Optional[str] = "1",
    page_size: Optional[str] = "15",
    db: Session = Depends(get_db),
):
    monthly_target = _safe_float(target, 100.0) or 100.0
    num_holdings = max(1, min(20, int(_safe_float(holdings, 6) or 6)))
    norm_asset = asset_type.strip().upper() if asset_type else None
    norm_currency = currency.strip().upper() if currency else None
    clean_tab = tab.strip().lower() if tab else "plan"
    active_tab = clean_tab if clean_tab in ("snapshot", "assets") else "plan"
    clean_market = market.strip().lower() if market else None

    # ponytail: subquery for latest close price per company; upgrade to materialized view if slow at scale
    latest_price_sq = (
        select(PriceHistory.close)
        .where(PriceHistory.company_id == Company.id)
        .order_by(PriceHistory.date.desc())
        .limit(1)
        .scalar_subquery()
    )

    stmt = (
        select(Company, DividendMetric, latest_price_sq.label("latest_price"))
        .join(DividendMetric, DividendMetric.company_id == Company.id)
        .where(
            DividendMetric.current_yield.is_not(None),
            DividendMetric.current_yield > 0,
            DividendMetric.current_yield <= 0.15,
            DividendMetric.is_suspect.is_(False),
            DividendMetric.annual_dividend.is_not(None),
            DividendMetric.annual_dividend > 0,
            latest_price_sq.is_not(None),
            latest_price_sq > 0,
        )
    )
    if clean_market:
        stmt = stmt.join(Exchange, Company.exchange_id == Exchange.id).where(StockService._market_clause(clean_market))
    if norm_asset in ("STOCK", "ETF"):
        stmt = stmt.where(Company.asset_type == norm_asset)
    if norm_currency:
        stmt = stmt.where(Company.currency == norm_currency)
    stmt = stmt.order_by(desc(DividendMetric.current_yield))

    candidates = db.execute(stmt).all()

    # Build full candidate pool with badges and standalone capital
    annual_target = monthly_target * 12
    pool: list[dict] = []
    prices_by_comp_id: dict[int, float] = {}
    for comp, metric, price in candidates:
        yld = metric.current_yield
        qual = metric.dividend_quality_score
        pay = metric.payout_ratio
        yrs_g = metric.years_growing
        pr = round(float(price), 2)
        prices_by_comp_id[comp.id] = pr
        badges: list[str] = []
        if yrs_g and yrs_g >= 25:
            badges.append("Aristocrat")
        elif yrs_g and yrs_g >= 10:
            badges.append("Growth")
        if pay is not None and pay <= 0.60:
            badges.append("Safe Payout")
        if yld >= 0.05:
            badges.append("High Yield")
        if qual and qual >= 80:
            badges.append("High Quality")
        # Standalone capital: how much to hit target with only this asset (annual_target / yield)
        standalone_capital = round(annual_target / yld, 0) if yld > 0 else 0
        annual_div = metric.annual_dividend or 0.0
        pool.append({
            "ticker": comp.ticker,
            "name": comp.name,
            "asset_type": comp.asset_type,
            "currency": comp.currency,
            "sector": comp.sector or "Unknown",
            "yield": yld,
            "annual_dividend": annual_div,
            "quality": qual,
            "payout_ratio": pay,
            "years_growing": yrs_g,
            "growth_3y": metric.growth_3y,
            "price": pr,
            "badges": badges,
            "standalone_capital": standalone_capital,
            "daily_income_per_share": round(annual_div / 365.0, 4),
            "daily_income_100": round((annual_div * 100.0) / 365.0, 2),
            "min_invest_1": pr,
            "min_invest_100": round(pr * 100.0, 2),
            "min_invest_target": standalone_capital,
        })

    # ponytail: greedy sector diversification (max 2 per sector); upgrade to LP solver if precision needed
    selected: list[dict] = []
    sector_count: dict[str, int] = {}
    for h in pool:
        if len(selected) >= num_holdings:
            break
        if sector_count.get(h["sector"], 0) >= 2:
            continue
        sector_count[h["sector"]] = sector_count.get(h["sector"], 0) + 1
        selected.append(h)

    per_asset_income = annual_target / max(len(selected), 1)

    holdings_result: list[dict] = []
    total_capital = 0.0
    total_income = 0.0
    for h in selected:
        shares = max(1, int(per_asset_income / h["annual_dividend"] + 0.5)) if h["annual_dividend"] > 0 else 1
        capital = round(shares * h["price"], 2)
        income = round(shares * h["annual_dividend"], 2)
        total_capital += capital
        total_income += income
        holdings_result.append({
            **h,
            "shares": shares,
            "capital": capital,
            "income": income,
            "monthly_income": round(income / 12, 2),
            "daily_income": round(income / 365, 2),
        })

    portfolio_yield = round((total_income / total_capital * 100) if total_capital > 0 else 0, 2)
    actual_monthly = round(total_income / 12, 2)
    actual_daily = round(total_income / 365, 2)

    # Snapshot data: upcoming ex-dividend events (next 7 days) and top high-yield + growth picks
    stock_service = StockService(db)
    today = date.today()
    next_week = today + timedelta(days=7)
    raw_events = stock_service.get_dividend_calendar(
        start_date=today,
        end_date=next_week,
        asset_type=norm_asset,
        currency=norm_currency,
        market=clean_market,
        limit=100,
    )
    upcoming_events: list[dict[str, Any]] = []
    for ev, comp in raw_events:
        pr = prices_by_comp_id.get(comp.id)
        amt = float(ev.amount) if ev.amount else 0.0
        upcoming_events.append({
            "ex_date": ev.ex_date,
            "payment_date": ev.payment_date,
            "ticker": comp.ticker,
            "name": comp.name,
            "asset_type": comp.asset_type,
            "currency": ev.currency or comp.currency,
            "amount": amt,
            "daily_income": round(amt / 365.0, 4),
            "price": pr,
        })

    # ponytail: rank score = yield% * (1 + years_growing*0.02) * (quality/100); swap to user weightings if requested
    def _growth_score(p: dict) -> float:
        yrs = p.get("years_growing") or 0
        qual = (p.get("quality") or 50) / 100.0
        return (p["yield"] * 100.0) * (1.0 + min(yrs, 25) * 0.02) * qual

    snapshot_picks = sorted(pool, key=_growth_score, reverse=True)[:30]

    # ponytail: in-memory pagination over candidate pool; upgrade to SQL offset/limit if pool > 10,000
    page_num = max(1, int(_safe_float(page, 1) or 1))
    size_num = max(1, min(100, int(_safe_float(page_size, 15) or 15)))
    pool_count = len(pool)
    pool_total_pages = max(1, (pool_count + size_num - 1) // size_num)
    if page_num > pool_total_pages:
        page_num = pool_total_pages
    paged_pool = pool[(page_num - 1) * size_num : page_num * size_num]
    pool_start = ((page_num - 1) * size_num + 1) if pool_count > 0 else 0
    pool_end = min(page_num * size_num, pool_count)

    currencies = stock_service.list_currencies(market=clean_market)
    planner_curr_sym = "₹" if clean_market == "india" else (currency_symbol(norm_currency) if norm_currency else "€")

    return templates.TemplateResponse(
        request=request,
        name="planner.html",
        context={
            "active_tab": "planner",
            "tab": active_tab,
            "target": monthly_target,
            "annual_target": round(annual_target, 2),
            "holdings": holdings_result,
            "num_holdings": num_holdings,
            "total_capital": round(total_capital, 2),
            "total_income": round(total_income, 2),
            "portfolio_yield": portfolio_yield,
            "actual_monthly": actual_monthly,
            "actual_daily": actual_daily,
            "selected_asset_type": asset_type or "",
            "selected_currency": currency or "",
            "selected_market": clean_market or "",
            "currencies": currencies,
            "planner_currency_symbol": planner_curr_sym,
            "pool": paged_pool,
            "pool_count": pool_count,
            "page": page_num,
            "page_size": size_num,
            "total_pages": pool_total_pages,
            "pool_start": pool_start,
            "pool_end": pool_end,
            "upcoming_events": upcoming_events,
            "snapshot_picks": snapshot_picks,
        },
    )

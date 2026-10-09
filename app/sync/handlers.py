import logging
from datetime import date, timedelta
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger("dividend_sync_worker")

from app.analytics.calculations import calculate_dividend_metrics
from app.db.models import Company, DividendMetric, Exchange, SyncJob
from app.db.repositories import (
    ChangeRepository,
    CompanyRepository,
    DividendRepository,
    ExchangeRepository,
    FinancialRepository,
    PriceRepository,
)
from app.sync.queue import SyncQueue
from app.sync.rate_limiter import RateLimiter
from app.yahoo.client import UpstreamThrottledError, YahooClient


# ponytail: simple dictionary alias mapping for Yahoo internal exchange codes; ceiling is manual aliases, upgrade to ISO 10383 MIC if multi-market expands
YAHOO_EXCHANGE_ALIASES: dict[str, str] = {
    "NYQ": "NYSE",
    "NYS": "NYSE",
    "ASE": "NYSE",
    "NMS": "NASDAQ",
    "NGM": "NASDAQ",
    "NCM": "NASDAQ",
    "PCX": "ARCA",
    "ARCX": "ARCA",
    "BATS": "ARCA",
    "GER": "FRA",
}


def _get_or_create_company(session: Session, ticker: str, exchange_code: Optional[str] = None) -> Company:
    comp_repo = CompanyRepository(session)
    company = comp_repo.get_by_ticker(ticker)
    if company:
        return company

    exch_repo = ExchangeRepository(session)
    raw_code = (exchange_code or "").upper().strip()
    canonical_code = YAHOO_EXCHANGE_ALIASES.get(raw_code, raw_code) or "NYSE"

    exch = exch_repo.get_by_code(canonical_code)
    if not exch:
        exch = exch_repo.get_by_code("NYSE")
    if not exch:
        exch = exch_repo.get_or_create(code=canonical_code, name=f"{canonical_code} Stock Exchange")

    comp, _ = comp_repo.upsert(ticker=ticker, name=ticker, exchange_id=exch.id)
    return comp


def update_analytics_for_company(session: Session, company_id: int) -> Optional[DividendMetric]:
    """Recalculates dividend metrics and records changes locally."""
    comp_repo = CompanyRepository(session)
    company = comp_repo.get_by_id(company_id)
    if not company:
        return None

    div_repo = DividendRepository(session)
    price_repo = PriceRepository(session)
    fin_repo = FinancialRepository(session)
    change_repo = ChangeRepository(session)

    events = div_repo.list_events(company_id=company_id, limit=500)
    latest_price_obj = price_repo.get_latest(company_id=company_id)
    latest_price = latest_price_obj.close if latest_price_obj else None
    fin_metric = fin_repo.get_by_company(company_id=company_id)

    computed = calculate_dividend_metrics(
        events=events,
        latest_price=latest_price,
        financial=fin_metric,
    )

    old_metric = div_repo.get_metric(company_id=company_id)

    # Detect notable changes before saving
    if old_metric:
        if old_metric.current_yield is not None and computed.current_yield is not None:
            if abs(computed.current_yield - old_metric.current_yield) >= 0.005:  # 0.5% yield shift
                change_repo.record_change(
                    entity_type="dividend_metric",
                    entity_id=company_id,
                    field_name="current_yield",
                    old_value=str(old_metric.current_yield),
                    new_value=str(computed.current_yield),
                )
        if old_metric.annual_dividend is not None and computed.annual_dividend is not None:
            if computed.annual_dividend > old_metric.annual_dividend:
                change_repo.record_change(
                    entity_type="dividend_metric",
                    entity_id=company_id,
                    field_name="annual_dividend",
                    old_value=str(old_metric.annual_dividend),
                    new_value=str(computed.annual_dividend),
                )
            elif computed.annual_dividend < old_metric.annual_dividend:
                change_repo.record_change(
                    entity_type="dividend_metric",
                    entity_id=company_id,
                    field_name="annual_dividend",
                    old_value=str(old_metric.annual_dividend),
                    new_value=str(computed.annual_dividend),
                )

    saved_metric = div_repo.upsert_metric(
        company_id=company_id,
        current_yield=computed.current_yield,
        trailing_yield=computed.trailing_yield,
        forward_yield=computed.forward_yield,
        annual_dividend=computed.annual_dividend,
        payout_ratio=computed.payout_ratio,
        fcf_coverage=computed.fcf_coverage,
        growth_1y=computed.growth_1y,
        growth_3y=computed.growth_3y,
        growth_5y=computed.growth_5y,
        growth_10y=computed.growth_10y,
        years_paying=computed.years_paying,
        years_growing=computed.years_growing,
        quality_score=computed.quality_score,
    )
    return saved_metric


def handle_sync_exchange(
    job: SyncJob,
    session: Session,
    yahoo: YahooClient,
    rate_limiter: RateLimiter,
    queue: SyncQueue,
) -> str:
    exchange_code = (job.ticker or "US").upper()
    rate_limiter.wait()

    exch_repo = ExchangeRepository(session)
    exch = exch_repo.get_by_code(exchange_code)
    if not exch:
        exch = exch_repo.get_or_create(code=exchange_code, name=f"{exchange_code} Stock Exchange")

    discovered = yahoo.discover_tickers(exchange_code)
    comp_repo = CompanyRepository(session)
    logger.info("Exchange %s discovered %d securities: %s", exchange_code, len(discovered), ", ".join(t.ticker for t in discovered))

    enqueued_count = 0
    for item in discovered:
        company, _ = comp_repo.upsert(
            ticker=item.ticker,
            name=item.name,
            exchange_id=exch.id,
            asset_type=item.asset_type,
        )
        queue.enqueue(
            session=session,
            job_type="SYNC_COMPANY",
            ticker=item.ticker,
            entity_type="company",
            entity_id=company.id,
            priority=8,
            parent_job_id=job.id,
        )
        enqueued_count += 1

    return f"Exchange {exchange_code} discovered: {len(discovered)} securities found, {enqueued_count} jobs enqueued"


def handle_sync_company(
    job: SyncJob,
    session: Session,
    yahoo: YahooClient,
    rate_limiter: RateLimiter,
    queue: SyncQueue,
) -> str:
    ticker = (job.ticker or "").upper()
    if not ticker:
        return "Skipped: missing ticker"

    rate_limiter.wait()
    profile = yahoo.get_company_profile(ticker)
    comp_repo = CompanyRepository(session)
    company = _get_or_create_company(session, ticker, profile.exchange_code if profile else None)

    if profile:
        comp_repo.upsert(
            ticker=ticker,
            name=profile.name,
            sector=profile.sector,
            industry=profile.industry,
            country=profile.country,
            currency=profile.currency,
            asset_type=profile.asset_type,
        )

    # Enqueue sub-jobs for dividends, prices, and financials
    for sub_job in ["SYNC_DIVIDENDS", "SYNC_PRICES", "SYNC_FINANCIALS"]:
        queue.enqueue(
            session=session,
            job_type=sub_job,
            ticker=ticker,
            entity_type="company",
            entity_id=company.id,
            priority=7,
            parent_job_id=job.parent_job_id or job.id,
        )

    return f"Synced company metadata for {ticker}"


def handle_sync_dividends(
    job: SyncJob,
    session: Session,
    yahoo: YahooClient,
    rate_limiter: RateLimiter,
    queue: SyncQueue,
) -> str:
    ticker = (job.ticker or "").upper()
    if not ticker:
        return "Skipped: missing ticker"

    rate_limiter.wait()
    company = _get_or_create_company(session, ticker)
    events = yahoo.get_dividends(ticker)

    div_repo = DividendRepository(session)
    inserted_count = 0
    for e in events:
        div_repo.upsert_event(
            company_id=company.id,
            ex_date=e.ex_date,
            pay_date=e.pay_date,
            amount=e.amount,
            currency=e.currency,
            frequency=e.frequency,
            status=e.status,
            source="yahoo",
        )
        inserted_count += 1

    # Recalculate analytics locally
    update_analytics_for_company(session, company.id)
    return f"Synced {inserted_count} dividend events for {ticker}"


def handle_sync_prices(
    job: SyncJob,
    session: Session,
    yahoo: YahooClient,
    rate_limiter: RateLimiter,
    queue: SyncQueue,
) -> str:
    ticker = (job.ticker or "").upper()
    if not ticker:
        return "Skipped: missing ticker"

    company = _get_or_create_company(session, ticker)
    price_repo = PriceRepository(session)

    # Incremental update: start from day after latest stored price
    latest_price = price_repo.get_latest(company.id)
    start_date = (latest_price.date + timedelta(days=1)) if latest_price else None

    # Skip if price history is already up-to-date through yesterday/today
    if start_date and start_date >= date.today():
        return f"Price history for {ticker} is already up to date"

    rate_limiter.wait()
    prices = yahoo.get_price_history(ticker, start=start_date)

    saved_count = 0
    for p in prices:
        price_repo.upsert_price(
            company_id=company.id,
            price_date=p.date,
            open_price=p.open,
            high=p.high,
            low=p.low,
            close=p.close,
            adj_close=p.adj_close,
            volume=p.volume,
        )
        saved_count += 1

    # Recalculate analytics locally with updated price
    update_analytics_for_company(session, company.id)
    return f"Synced {saved_count} price rows for {ticker}"


def handle_sync_financials(
    job: SyncJob,
    session: Session,
    yahoo: YahooClient,
    rate_limiter: RateLimiter,
    queue: SyncQueue,
) -> str:
    ticker = (job.ticker or "").upper()
    if not ticker:
        return "Skipped: missing ticker"

    rate_limiter.wait()
    fin_data = yahoo.get_financials(ticker)
    company = _get_or_create_company(session, ticker)

    fin_repo = FinancialRepository(session)
    fin_repo.upsert_metrics(
        company_id=company.id,
        market_cap=fin_data.market_cap,
        pe_ratio=fin_data.pe_ratio,
        forward_pe=fin_data.forward_pe,
        pb_ratio=fin_data.pb_ratio,
        debt_to_equity=fin_data.debt_to_equity,
        roe=fin_data.roe,
        roa=fin_data.roa,
        earnings_growth=fin_data.earnings_growth,
        revenue_growth=fin_data.revenue_growth,
        free_cash_flow=fin_data.free_cash_flow,
        operating_cash_flow=fin_data.operating_cash_flow,
    )

    update_analytics_for_company(session, company.id)
    return f"Synced financials for {ticker}"


def handle_calculate_analytics(
    job: SyncJob,
    session: Session,
    yahoo: YahooClient,
    rate_limiter: RateLimiter,
    queue: SyncQueue,
) -> str:
    company_id = job.entity_id
    if not company_id and job.ticker:
        company = CompanyRepository(session).get_by_ticker(job.ticker)
        company_id = company.id if company else None

    if not company_id:
        return "Skipped: missing company"

    metric = update_analytics_for_company(session, company_id)
    return f"Calculated analytics for company {company_id}: score={metric.quality_score if metric else None}"


JOB_HANDLERS = {
    "SYNC_EXCHANGE": handle_sync_exchange,
    "DISCOVER_EXCHANGE": handle_sync_exchange,
    "SYNC_COMPANY": handle_sync_company,
    "SYNC_DIVIDENDS": handle_sync_dividends,
    "SYNC_PRICES": handle_sync_prices,
    "SYNC_FINANCIALS": handle_sync_financials,
    "CALCULATE_ANALYTICS": handle_calculate_analytics,
}


def dispatch_job(
    job: SyncJob,
    session: Session,
    yahoo: YahooClient,
    rate_limiter: RateLimiter,
    queue: SyncQueue,
) -> str:
    handler = JOB_HANDLERS.get(job.job_type)
    if not handler:
        raise ValueError(f"Unknown job type: {job.job_type}")
    return handler(job, session, yahoo, rate_limiter, queue)

"""Pydantic schemas for /api/v1 REST endpoints."""

from datetime import date, datetime
from typing import Generic, Optional, TypeVar
from pydantic import BaseModel, ConfigDict, Field

from app.db.models import utcnow

T = TypeVar("T")


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PaginatedResponse(BaseSchema, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int
    as_of: datetime = Field(default_factory=utcnow)


class ExchangeOut(BaseSchema):
    id: int
    code: str
    name: str
    country: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DividendMetricSummary(BaseSchema):
    current_yield: Optional[float] = None
    trailing_yield: Optional[float] = None
    forward_yield: Optional[float] = None
    annual_dividend: Optional[float] = None
    payout_ratio: Optional[float] = None
    growth_1y: Optional[float] = None
    growth_3y: Optional[float] = None
    growth_5y: Optional[float] = None
    years_paying: Optional[int] = None
    years_growing: Optional[int] = None
    quality_score: Optional[float] = None
    calculated_at: Optional[datetime] = None


class PriceSummary(BaseSchema):
    date: date
    close: Optional[float] = None
    adj_close: Optional[float] = None
    volume: Optional[int] = None


class CompanySummaryOut(BaseSchema):
    id: int
    ticker: str
    name: str
    exchange_code: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = None
    asset_type: str = "STOCK"
    is_active: bool
    current_yield: Optional[float] = None
    quality_score: Optional[float] = None


class CompanyDetailOut(BaseSchema):
    id: int
    ticker: str
    name: str
    exchange_code: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = None
    asset_type: str = "STOCK"
    is_active: bool
    created_at: datetime
    updated_at: datetime
    dividend_metric: Optional[DividendMetricSummary] = None
    latest_price: Optional[PriceSummary] = None
    as_of: datetime = Field(default_factory=utcnow)


class DividendEventOut(BaseSchema):
    id: int
    company_id: int
    ticker: str
    ex_date: Optional[date] = None
    record_date: Optional[date] = None
    pay_date: Optional[date] = None
    declaration_date: Optional[date] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    event_type: Optional[str] = "REGULAR"
    status: str
    frequency: Optional[str] = None
    created_at: datetime


class DividendMetricOut(BaseSchema):
    id: int
    company_id: int
    ticker: str
    current_yield: Optional[float] = None
    trailing_yield: Optional[float] = None
    forward_yield: Optional[float] = None
    annual_dividend: Optional[float] = None
    payout_ratio: Optional[float] = None
    fcf_coverage: Optional[float] = None
    growth_1y: Optional[float] = None
    growth_3y: Optional[float] = None
    growth_5y: Optional[float] = None
    growth_10y: Optional[float] = None
    years_paying: Optional[int] = None
    years_growing: Optional[int] = None
    quality_score: Optional[float] = None
    calculated_at: Optional[datetime] = None


class PriceHistoryOut(BaseSchema):
    id: int
    company_id: int
    ticker: str
    date: date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    adj_close: Optional[float] = None
    volume: Optional[int] = None


class FinancialMetricOut(BaseSchema):
    id: int
    company_id: int
    ticker: str
    fiscal_year: Optional[int] = None
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    eps: Optional[float] = None
    fcf: Optional[float] = None
    debt_to_equity: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    calculated_at: Optional[datetime] = None


class IndustrySummaryOut(BaseSchema):
    sector: str
    industry: str
    company_count: int
    avg_yield: Optional[float] = None
    median_yield: Optional[float] = None
    avg_quality_score: Optional[float] = None
    top_tickers: list[str] = Field(default_factory=list)


class CompetitorPeerOut(BaseSchema):
    ticker: str
    name: str
    current_yield: Optional[float] = None
    payout_ratio: Optional[float] = None
    growth_3y: Optional[float] = None
    quality_score: Optional[float] = None
    pe_ratio: Optional[float] = None


class CompetitorComparisonOut(BaseSchema):
    target: CompetitorPeerOut
    peers: list[CompetitorPeerOut]
    industry: Optional[str] = None
    sector: Optional[str] = None
    industry_avg_yield: Optional[float] = None
    industry_avg_quality: Optional[float] = None
    as_of: datetime = Field(default_factory=utcnow)


class SyncJobOut(BaseSchema):
    id: int
    job_type: str
    ticker: Optional[str] = None
    exchange_code: Optional[str] = None
    status: str
    attempts: int
    max_attempts: int
    priority: int
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    next_run_at: Optional[datetime] = None
    locked_at: Optional[datetime] = None


class SyncRunOut(BaseSchema):
    id: int
    run_type: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    items_processed: int
    items_failed: int
    error: Optional[str] = None


class WorkerStatusOut(BaseSchema):
    id: int
    worker_id: str
    status: str
    current_job_id: Optional[int] = None
    heartbeat_at: datetime


class SyncStatusOverviewOut(BaseSchema):
    workers: list[WorkerStatusOut]
    queue_stats: dict[str, int]
    recent_runs: list[SyncRunOut]
    as_of: datetime = Field(default_factory=utcnow)


class DataChangeOut(BaseSchema):
    id: int
    run_id: Optional[int] = None
    entity_type: str
    entity_id: int
    field_name: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    detected_at: datetime

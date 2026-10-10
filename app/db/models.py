from datetime import date, datetime, timezone
from typing import Any, Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Exchange(Base):
    __tablename__ = "exchanges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    country: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    companies: Mapped[list["Company"]] = relationship("Company", back_populates="exchange")

    @property
    def last_synced_at(self) -> Optional[datetime]:
        # ponytail: dynamic lookup via sync jobs or None; avoid fake updated_at timestamps
        return None



class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("exchange_id", "ticker", name="uq_exchange_ticker"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    exchange_id: Mapped[int] = mapped_column(Integer, ForeignKey("exchanges.id"), index=True)
    name: Mapped[str] = mapped_column(String(256))
    sector: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    industry: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    country: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    asset_type: Mapped[str] = mapped_column(String(16), default="STOCK", server_default="STOCK", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    exchange: Mapped["Exchange"] = relationship("Exchange", back_populates="companies")
    dividend_events: Mapped[list["DividendEvent"]] = relationship("DividendEvent", back_populates="company", cascade="all, delete-orphan")
    dividend_metric: Mapped[Optional["DividendMetric"]] = relationship("DividendMetric", back_populates="company", uselist=False, cascade="all, delete-orphan")
    financial_metric: Mapped[Optional["FinancialMetric"]] = relationship("FinancialMetric", back_populates="company", uselist=False, cascade="all, delete-orphan")
    price_history: Mapped[list["PriceHistory"]] = relationship("PriceHistory", back_populates="company", cascade="all, delete-orphan")
    relationships: Mapped[list["CompanyRelationship"]] = relationship("CompanyRelationship", foreign_keys="CompanyRelationship.company_id", back_populates="company")

    @property
    def exchange_code(self) -> Optional[str]:
        return self.exchange.code if self.exchange else None

    @property
    def metric(self) -> Optional["DividendMetric"]:
        return self.dividend_metric

    @property
    def market_cap(self) -> Optional[float]:
        return self.financial_metric.market_cap if self.financial_metric else None

    @property
    def latest_price(self) -> Optional[float]:
        # ponytail: latest close price from relationship; upgrade: denormalized column on company if large scale
        if self.price_history:
            return max(self.price_history, key=lambda p: p.date).close
        return None



class DividendEvent(Base):
    __tablename__ = "dividend_events"
    __table_args__ = (
        UniqueConstraint("company_id", "ex_date", "pay_date", "amount", name="uq_company_dividend_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id"), index=True)
    declaration_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    ex_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    record_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    pay_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    frequency: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTUAL")
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    company: Mapped["Company"] = relationship("Company", back_populates="dividend_events")

    @property
    def ticker(self) -> str:
        return self.company.ticker if self.company else ""

    @property
    def payment_date(self) -> Optional[date]:
        return self.pay_date


class DividendMetric(Base):
    __tablename__ = "dividend_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id"), unique=True, index=True)
    current_yield: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trailing_yield: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    forward_yield: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    annual_dividend: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    payout_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fcf_coverage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    growth_1y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    growth_3y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    growth_5y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    growth_10y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    years_paying: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    years_growing: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    calculated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    company: Mapped["Company"] = relationship("Company", back_populates="dividend_metric")

    @property
    def ticker(self) -> str:
        return self.company.ticker if self.company else ""

    @property
    def dividend_growth_3y(self) -> Optional[float]:
        return self.growth_3y

    @property
    def dividend_quality_score(self) -> Optional[float]:
        return self.quality_score

    @property
    def free_cash_flow_coverage(self) -> Optional[float]:
        return self.fcf_coverage

    @property
    def trailing_annual_dividend_yield(self) -> Optional[float]:
        return self.trailing_yield

    @property
    def forward_annual_dividend_yield(self) -> Optional[float]:
        return self.forward_yield

    @property
    def payment_frequency(self) -> str:
        # ponytail: infer frequency from event count in latest completed year; upgrade to calendar analysis if irregular
        if not self.company or not self.company.dividend_events:
            return "Quarterly"
        actual_events = [e for e in self.company.dividend_events if e.status == "ACTUAL" and e.ex_date]
        if not actual_events:
            return "Quarterly"
        by_year: dict[int, int] = {}
        for e in actual_events:
            by_year[e.ex_date.year] = by_year.get(e.ex_date.year, 0) + 1
        today_year = date.today().year
        completed_years = [y for y in sorted(by_year.keys()) if y < today_year]
        ref_year = completed_years[-1] if completed_years else max(by_year.keys())
        count = by_year[ref_year]
        if count == 1:
            return "Annual"
        elif count == 2:
            return "Semiannual"
        elif count in (3, 4):
            return "Quarterly"
        elif count >= 10:
            return "Monthly"
        return "Quarterly"


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("company_id", "date", name="uq_company_price_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    adj_close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    company: Mapped["Company"] = relationship("Company", back_populates="price_history")

    @property
    def ticker(self) -> str:
        return self.company.ticker if self.company else ""

    @property
    def price_date(self) -> date:
        return self.date

    @property
    def close_price(self) -> Optional[float]:
        return self.close

    @property
    def open_price(self) -> Optional[float]:
        return self.open

    @property
    def high_price(self) -> Optional[float]:
        return self.high

    @property
    def low_price(self) -> Optional[float]:
        return self.low


class FinancialMetric(Base):
    __tablename__ = "financial_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id"), unique=True, index=True)
    market_cap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pe_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    forward_pe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pb_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    debt_to_equity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    roe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    roa: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    earnings_growth: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    revenue_growth: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    free_cash_flow: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    operating_cash_flow: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    calculated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    company: Mapped["Company"] = relationship("Company", back_populates="financial_metric")

    @property
    def ticker(self) -> str:
        return self.company.ticker if self.company else ""

    @property
    def trailing_pe(self) -> Optional[float]:
        return self.pe_ratio

    @trailing_pe.setter
    def trailing_pe(self, value: Optional[float]) -> None:
        self.pe_ratio = value

    @property
    def price_to_book(self) -> Optional[float]:
        return self.pb_ratio

    @price_to_book.setter
    def price_to_book(self, value: Optional[float]) -> None:
        self.pb_ratio = value

    @property
    def as_of_date(self) -> Optional[datetime]:
        return self.calculated_at

    @as_of_date.setter
    def as_of_date(self, value: Optional[datetime]) -> None:
        self.calculated_at = value


class CompanyRelationship(Base):
    __tablename__ = "company_relationships"
    __table_args__ = (
        UniqueConstraint("company_id", "related_company_id", "relationship_type", name="uq_company_relationship"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id"), index=True)
    related_company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id"), index=True)
    relationship_type: Mapped[str] = mapped_column(String(32), default="competitor")
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    company: Mapped["Company"] = relationship("Company", foreign_keys=[company_id], back_populates="relationships")
    related_company: Mapped["Company"] = relationship("Company", foreign_keys=[related_company_id])


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ticker: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    parent_job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sync_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=10, index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    locked_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    items_processed: Mapped[int] = mapped_column(Integer, default=0)
    items_failed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    @property
    def finished_at(self) -> Optional[datetime]:
        return self.completed_at


class WorkerStatus(Base):
    __tablename__ = "worker_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="IDLE")
    current_job_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    @property
    def last_heartbeat(self) -> datetime:
        return self.heartbeat_at

    @property
    def hostname(self) -> str:
        return "localhost"

    @property
    def pid(self) -> int:
        return 0


class SyncState(Base):
    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    value_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class DataChange(Base):
    __tablename__ = "data_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    field_name: Mapped[str] = mapped_column(String(64))
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def __init__(self, **kwargs: Any) -> None:
        ticker_val = kwargs.pop("ticker", None)
        change_type_val = kwargs.pop("change_type", None)
        if change_type_val and "field_name" not in kwargs:
            kwargs["field_name"] = change_type_val
        if "entity_type" not in kwargs:
            kwargs["entity_type"] = "company"
        if "entity_id" not in kwargs:
            kwargs["entity_id"] = 0
        super().__init__(**kwargs)
        self._ticker = ticker_val

    @property
    def ticker(self) -> str:
        if hasattr(self, "_ticker") and self._ticker:
            return self._ticker
        return f"Company #{self.entity_id}"

    @ticker.setter
    def ticker(self, val: str) -> None:
        self._ticker = val

    @property
    def change_type(self) -> str:
        if self.field_name == "annual_dividend":
            try:
                ov = float(self.old_value) if self.old_value else 0.0
                nv = float(self.new_value) if self.new_value else 0.0
                if nv > ov:
                    return "dividend_increase"
                elif nv < ov:
                    return "dividend_cut"
            except (ValueError, TypeError):
                pass
            return "dividend_change"
        if "yield" in self.field_name:
            return "yield_shift"
        return self.field_name


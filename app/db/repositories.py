from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Sequence
from sqlalchemy import desc, exists, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Company,
    CompanyRelationship,
    DataChange,
    DividendEvent,
    DividendMetric,
    Exchange,
    FinancialMetric,
    PriceHistory,
    SyncJob,
    SyncRun,
    SyncState,
    WorkerStatus,
    utcnow,
)


class ExchangeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, exchange_id: int) -> Optional[Exchange]:
        return self.session.get(Exchange, exchange_id)

    def get_by_code(self, code: str) -> Optional[Exchange]:
        stmt = select(Exchange).where(Exchange.code == code.upper())
        return self.session.execute(stmt).scalar_one_or_none()

    def list_all(self, active_only: bool = True) -> Sequence[Exchange]:
        stmt = select(Exchange)
        if active_only:
            stmt = stmt.where(Exchange.is_active.is_(True))
        stmt = stmt.order_by(Exchange.code)
        return self.session.execute(stmt).scalars().all()

    def get_or_create(
        self,
        code: str,
        name: str,
        country: Optional[str] = None,
        currency: Optional[str] = None,
        timezone: Optional[str] = None,
        timezone_str: Optional[str] = None,
        is_active: bool = True,
    ) -> Exchange:
        code_upper = code.upper()
        existing = self.get_by_code(code_upper)
        if existing:
            return existing
        return self.upsert(
            code=code,
            name=name,
            country=country,
            currency=currency,
            timezone=timezone,
            timezone_str=timezone_str,
            is_active=is_active,
        )

    def upsert(
        self,
        code: str,
        name: str,
        country: Optional[str] = None,
        currency: Optional[str] = None,
        timezone: Optional[str] = None,
        timezone_str: Optional[str] = None,
        is_active: bool = True,
    ) -> Exchange:
        code_upper = code.upper()
        resolved_tz = timezone or timezone_str
        exchange = self.get_by_code(code_upper)
        if exchange:
            if name:
                exchange.name = name
            if country is not None:
                exchange.country = country
            if currency is not None:
                exchange.currency = currency
            if resolved_tz is not None:
                exchange.timezone = resolved_tz
            exchange.is_active = is_active
            exchange.updated_at = utcnow()
        else:
            exchange = Exchange(
                code=code_upper,
                name=name,
                country=country,
                currency=currency,
                timezone=resolved_tz,
                is_active=is_active,
            )
            self.session.add(exchange)
        self.session.flush()
        return exchange


class CompanyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, company_id: int) -> Optional[Company]:
        return self.session.get(Company, company_id)

    def get_by_ticker(self, ticker: str, exchange_id: Optional[int] = None) -> Optional[Company]:
        stmt = select(Company).where(Company.ticker == ticker.upper())
        if exchange_id is not None:
            stmt = stmt.where(Company.exchange_id == exchange_id)
        return self.session.execute(stmt).scalars().first()

    def _filter_companies(
        self,
        stmt: Any,
        exchange_id: Optional[int] = None,
        sector: Optional[str] = None,
        industry: Optional[str] = None,
        asset_type: Optional[str] = None,
        search: Optional[str] = None,
        is_active: Optional[bool] = True,
        sync_state: Optional[str] = None,
    ) -> Any:
        if exchange_id is not None:
            stmt = stmt.where(Company.exchange_id == exchange_id)
        if sector:
            stmt = stmt.where(Company.sector == sector)
        if industry:
            stmt = stmt.where(Company.industry == industry)
        if asset_type:
            stmt = stmt.where(Company.asset_type == asset_type.upper().strip())
        if is_active is not None:
            stmt = stmt.where(Company.is_active.is_(is_active))
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(Company.ticker.ilike(pattern) | Company.name.ilike(pattern))
        if sync_state == "never":
            stmt = stmt.where(Company.last_synced_at.is_(None))
        elif sync_state == "stale_7":
            stmt = stmt.where(Company.last_synced_at < utcnow() - timedelta(days=7))
        elif sync_state == "stale_30":
            stmt = stmt.where(Company.last_synced_at < utcnow() - timedelta(days=30))
        elif sync_state == "failed":
            # ponytail: subquery match on ticker; assumes unique tickers across active exchanges
            stmt = stmt.where(
                exists().where(SyncJob.ticker == Company.ticker, SyncJob.status == "FAILED")
            )
        return stmt

    def list_companies(
        self,
        exchange_id: Optional[int] = None,
        sector: Optional[str] = None,
        industry: Optional[str] = None,
        asset_type: Optional[str] = None,
        search: Optional[str] = None,
        is_active: Optional[bool] = True,
        sync_state: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Company]:
        stmt = self._filter_companies(
            select(Company),
            exchange_id=exchange_id,
            sector=sector,
            industry=industry,
            asset_type=asset_type,
            search=search,
            is_active=is_active,
            sync_state=sync_state,
        )
        stmt = stmt.order_by(Company.ticker).limit(limit).offset(offset)
        return self.session.execute(stmt).scalars().all()

    def count_companies(
        self,
        exchange_id: Optional[int] = None,
        sector: Optional[str] = None,
        industry: Optional[str] = None,
        asset_type: Optional[str] = None,
        search: Optional[str] = None,
        is_active: Optional[bool] = True,
        sync_state: Optional[str] = None,
    ) -> int:
        stmt = self._filter_companies(
            select(func.count(Company.id)),
            exchange_id=exchange_id,
            sector=sector,
            industry=industry,
            asset_type=asset_type,
            search=search,
            is_active=is_active,
            sync_state=sync_state,
        )
        return self.session.execute(stmt).scalar() or 0

    def list_by_exchange(self, exchange_id: int) -> Sequence[Company]:
        return self.list_companies(exchange_id=exchange_id, limit=10000)

    def upsert(
        self,
        ticker: str,
        name_or_exchange: Any = None,
        exchange_id: Optional[int] = None,
        name: Optional[str] = None,
        sector: Optional[str] = None,
        industry: Optional[str] = None,
        country: Optional[str] = None,
        currency: Optional[str] = None,
        asset_type: Optional[str] = None,
        is_active: bool = True,
    ) -> tuple[Company, bool]:
        """Returns (company, created_bool). Supports flexible positional or keyword signatures."""
        ticker_upper = ticker.upper()

        if isinstance(name_or_exchange, int):
            real_exchange_id = name_or_exchange
            real_name = name or ticker_upper
        else:
            real_name = str(name_or_exchange) if name_or_exchange is not None else (name or ticker_upper)
            real_exchange_id = exchange_id

        if real_exchange_id is None:
            existing = self.get_by_ticker(ticker_upper)
            if existing:
                real_exchange_id = existing.exchange_id
            else:
                first_exch = self.session.execute(select(Exchange.id)).scalar_one_or_none()
                real_exchange_id = first_exch or 1

        stmt = select(Company).where(
            Company.exchange_id == real_exchange_id,
            Company.ticker == ticker_upper,
        )
        company = self.session.execute(stmt).scalar_one_or_none()
        created = False
        if company:
            company.name = real_name
            if sector is not None:
                company.sector = sector
            if industry is not None:
                company.industry = industry
            if country is not None:
                company.country = country
            if currency is not None:
                company.currency = currency
            if asset_type is not None:
                company.asset_type = asset_type
            company.is_active = is_active
            company.updated_at = utcnow()
        else:
            company = Company(
                ticker=ticker_upper,
                exchange_id=real_exchange_id,
                name=real_name,
                sector=sector,
                industry=industry,
                country=country,
                currency=currency,
                asset_type=asset_type or "STOCK",
                is_active=is_active,
            )
            self.session.add(company)
            created = True
        self.session.flush()
        return company, created

    def mark_synced(self, company_id: int, timestamp: Optional[datetime] = None) -> None:
        company = self.get_by_id(company_id)
        if company:
            company.last_synced_at = timestamp or utcnow()
            company.updated_at = utcnow()
            self.session.flush()

    def list_sectors(self) -> Sequence[str]:
        stmt = (
            select(Company.sector)
            .where(Company.sector.is_not(None))
            .distinct()
            .order_by(Company.sector)
        )
        return [s for s in self.session.execute(stmt).scalars().all() if s]

    def list_industries(self, sector: Optional[str] = None) -> Sequence[str]:
        stmt = select(Company.industry).where(Company.industry.is_not(None))
        if sector:
            stmt = stmt.where(Company.sector == sector)
        stmt = stmt.distinct().order_by(Company.industry)
        return [ind for ind in self.session.execute(stmt).scalars().all() if ind]


class DividendRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_by_company(self, company_id: int, limit: int = 100) -> Sequence[DividendEvent]:
        stmt = (
            select(DividendEvent)
            .where(DividendEvent.company_id == company_id)
            .order_by(desc(DividendEvent.ex_date), desc(DividendEvent.pay_date))
            .limit(limit)
        )
        return self.session.execute(stmt).scalars().all()

    list_events = list_by_company

    def get_latest_event(self, company_id: int) -> Optional[DividendEvent]:
        stmt = (
            select(DividendEvent)
            .where(DividendEvent.company_id == company_id)
            .order_by(desc(DividendEvent.ex_date))
            .limit(1)
        )
        return self.session.execute(stmt).scalars().first()

    def upsert_event(
        self,
        company_id: int,
        ex_date: Optional[date],
        pay_date: Optional[date],
        amount: Optional[float],
        declaration_date: Optional[date] = None,
        record_date: Optional[date] = None,
        currency: Optional[str] = None,
        frequency: Optional[str] = None,
        status: str = "ACTUAL",
        source: Optional[str] = "yfinance",
        fetched_at: Optional[datetime] = None,
    ) -> tuple[DividendEvent, bool]:
        stmt = select(DividendEvent).where(
            DividendEvent.company_id == company_id,
            DividendEvent.ex_date == ex_date,
            DividendEvent.pay_date == pay_date,
            DividendEvent.amount == amount,
        )
        event = self.session.execute(stmt).scalar_one_or_none()
        created = False
        if event:
            event.declaration_date = declaration_date
            event.record_date = record_date
            event.currency = currency
            event.frequency = frequency
            event.status = status
            event.source = source
            event.fetched_at = fetched_at or utcnow()
        else:
            event = DividendEvent(
                company_id=company_id,
                declaration_date=declaration_date,
                ex_date=ex_date,
                record_date=record_date,
                pay_date=pay_date,
                amount=amount,
                currency=currency,
                frequency=frequency,
                status=status,
                source=source,
                fetched_at=fetched_at or utcnow(),
            )
            self.session.add(event)
            created = True
        self.session.flush()
        return event, created

    def get_metric(self, company_id: int) -> Optional[DividendMetric]:
        stmt = select(DividendMetric).where(DividendMetric.company_id == company_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert_metric(self, company_id: int, **metrics: Any) -> DividendMetric:
        metric = self.get_metric(company_id)
        if not metric:
            metric = DividendMetric(company_id=company_id)
            self.session.add(metric)
        for key, value in metrics.items():
            if hasattr(metric, key):
                setattr(metric, key, value)
        metric.calculated_at = utcnow()
        self.session.flush()
        return metric


class PriceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_history(
        self,
        company_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: Optional[int] = None,
    ) -> Sequence[PriceHistory]:
        stmt = select(PriceHistory).where(PriceHistory.company_id == company_id)
        if start_date:
            stmt = stmt.where(PriceHistory.date >= start_date)
        if end_date:
            stmt = stmt.where(PriceHistory.date <= end_date)
        stmt = stmt.order_by(desc(PriceHistory.date))
        if limit:
            stmt = stmt.limit(limit)
        return self.session.execute(stmt).scalars().all()

    def get_latest_price(self, company_id: int) -> Optional[PriceHistory]:
        stmt = (
            select(PriceHistory)
            .where(PriceHistory.company_id == company_id)
            .order_by(desc(PriceHistory.date))
            .limit(1)
        )
        return self.session.execute(stmt).scalars().first()

    get_latest = get_latest_price

    def upsert_price(
        self,
        company_id: int,
        price_date: Optional[date] = None,
        date: Optional[date] = None,
        open_price: Optional[float] = None,
        open: Optional[float] = None,
        high_price: Optional[float] = None,
        high: Optional[float] = None,
        low_price: Optional[float] = None,
        low: Optional[float] = None,
        close_price: Optional[float] = None,
        close: Optional[float] = None,
        adj_close: Optional[float] = None,
        volume: Optional[int] = None,
    ) -> tuple[PriceHistory, bool]:
        dt = price_date if price_date is not None else date
        if dt is None:
            raise ValueError("Either price_date or date must be provided")
        op = open_price if open_price is not None else open
        hp = high_price if high_price is not None else high
        lp = low_price if low_price is not None else low
        cp = close_price if close_price is not None else close

        stmt = select(PriceHistory).where(
            PriceHistory.company_id == company_id,
            PriceHistory.date == dt,
        )
        record = self.session.execute(stmt).scalar_one_or_none()
        created = False
        if record:
            record.open = op
            record.high = hp
            record.low = lp
            record.close = cp
            record.adj_close = adj_close
            record.volume = volume
        else:
            record = PriceHistory(
                company_id=company_id,
                date=dt,
                open=op,
                high=hp,
                low=lp,
                close=cp,
                adj_close=adj_close,
                volume=volume,
            )
            self.session.add(record)
            created = True
        self.session.flush()
        return record, created


class FinancialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_metric(self, company_id: int) -> Optional[FinancialMetric]:
        stmt = select(FinancialMetric).where(FinancialMetric.company_id == company_id)
        return self.session.execute(stmt).scalar_one_or_none()

    get_by_company = get_metric

    def upsert_metric(self, company_id: int, **metrics: Any) -> FinancialMetric:
        metric = self.get_metric(company_id)
        if not metric:
            metric = FinancialMetric(company_id=company_id)
            self.session.add(metric)
        for key, value in metrics.items():
            if hasattr(metric, key):
                setattr(metric, key, value)
        metric.calculated_at = utcnow()
        self.session.flush()
        return metric

    upsert_metrics = upsert_metric


class ChangeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record_change(
        self,
        entity_type: str,
        entity_id: int,
        field_name: str,
        old_value: Optional[Any],
        new_value: Optional[Any],
        run_id: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> Optional[DataChange]:
        # Only record if values actually differ
        old_str = None if old_value is None else str(old_value)
        new_str = None if new_value is None else str(new_value)
        if old_str == new_str:
            return None

        change = DataChange(
            run_id=run_id,
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
            old_value=old_str,
            new_value=new_str,
            detected_at=utcnow(),
        )
        self.session.add(change)
        self.session.flush()
        return change

    def record_diff(
        self,
        entity_type: str,
        entity_id: int,
        old_data: dict[str, Any],
        new_data: dict[str, Any],
        run_id: Optional[int] = None,
    ) -> list[DataChange]:
        changes: list[DataChange] = []
        all_keys = set(old_data.keys()) | set(new_data.keys())
        for key in sorted(all_keys):
            old_val = old_data.get(key)
            new_val = new_data.get(key)
            change = self.record_change(
                entity_type=entity_type,
                entity_id=entity_id,
                field_name=key,
                old_value=old_val,
                new_value=new_val,
                run_id=run_id,
            )
            if change:
                changes.append(change)
        return changes

    def list_recent(
        self,
        limit: int = 50,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        change_type: Optional[str] = None,
    ) -> Sequence[DataChange]:
        stmt = select(DataChange)
        if entity_type:
            stmt = stmt.where(DataChange.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(DataChange.entity_id == entity_id)
        if change_type:
            if change_type in ("dividend_increase", "dividend_cut"):
                stmt = stmt.where(DataChange.field_name == "annual_dividend")
            elif change_type == "yield_shift":
                stmt = stmt.where(DataChange.field_name.like("%yield%"))
            else:
                stmt = stmt.where(DataChange.field_name == change_type)
        stmt = stmt.order_by(desc(DataChange.detected_at)).limit(limit)
        changes = list(self.session.execute(stmt).scalars().all())
        if changes:
            company_ids = {c.entity_id for c in changes if c.entity_id}
            if company_ids:
                comp_stmt = select(Company.id, Company.ticker).where(Company.id.in_(company_ids))
                comp_map = dict(self.session.execute(comp_stmt).all())
                for c in changes:
                    if c.entity_id in comp_map:
                        c._ticker = comp_map[c.entity_id]
        return changes


class SyncStateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_value(self, key: str) -> Optional[str]:
        stmt = select(SyncState.value_json).where(SyncState.key == key)
        return self.session.execute(stmt).scalar_one_or_none()

    def set_value(self, key: str, value_json: str) -> SyncState:
        stmt = select(SyncState).where(SyncState.key == key)
        state = self.session.execute(stmt).scalar_one_or_none()
        if state:
            state.value_json = value_json
            state.updated_at = utcnow()
        else:
            state = SyncState(key=key, value_json=value_json)
            self.session.add(state)
        self.session.flush()
        return state

# Dividend Explorer

## OpenCode Project Context

This repository implements Dividend Explorer, a lightweight dividend-stock discovery and analytics application.

### Core stack

- Python 3.12+
- FastAPI
- SQLAlchemy
- SQLite
- Alembic
- yfinance
- Jinja2
- HTMX
- Chart.js
- Custom Python background worker
- SQLite-backed persistent job queue
- Native deployment; no Docker in V1

### Architecture

```text
Browser
   │ HTTP/HTMX
   ▼
FastAPI
   │
   ▼
Application Services
   │
   ▼
SQLite
   ▲
   │
Sync Worker
   │
yfinance
   │
Yahoo Finance
```

### Important boundary

Yahoo Finance/yfinance is an ingestion source only. SQLite is the application's operational source of truth.

The normal web UI and REST API must never call Yahoo Finance directly. They read from SQLite through application services.

### V1 constraints

Do not introduce:

- Docker
- Kubernetes
- Celery
- Redis
- RabbitMQ
- PostgreSQL
- Microservices

The architecture should remain extensible so these can be introduced later if needed.

### Synchronization

The worker must:

1. Discover securities exchange by exchange.
2. Persist jobs in SQLite.
3. Process jobs asynchronously.
4. Resume after restart.
5. Randomize exchange/job ordering for traffic smoothing.
6. Use configurable request delays/jitter.
7. Enforce conservative rate limiting.
8. Use exponential backoff with jitter.
9. Persist successful work immediately.
10. Stop or pause rather than aggressively retry when upstream throttling occurs.
11. Detect changes between stored and newly retrieved values.
12. Recalculate affected analytics locally.

Randomization and rate limiting are for traffic smoothing and workload control. Do not implement proxy rotation, fingerprint spoofing, CAPTCHA bypass, or other anti-bot evasion.

### Data model

Primary tables:

- exchanges
- companies
- dividend_events
- dividend_metrics
- price_history
- financial_metrics
- company_relationships
- sync_jobs
- sync_runs
- worker_status
- sync_state
- data_changes

SQLite should use:

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
```

### API

Expose versioned read-only REST APIs under `/api/v1`.

API groups:

- exchanges
- companies/stocks
- dividends
- dividend metrics
- prices
- financials
- industries
- competitors
- analytics
- synchronization status
- change history

FastAPI must expose:

- `/docs`
- `/redoc`
- `/openapi.json`

API requests must not trigger live Yahoo requests.

### UI

Use a lightweight Jinja2 + HTMX interface.

Required views:

- dashboard
- stock search
- stock detail
- industry explorer
- competitor comparison
- dividend calendar
- analytics
- sync dashboard
- exchange sync detail
- change dashboard

The sync dashboard can poll with HTMX every 5 seconds. WebSockets are not required for V1.

### Analytics

Calculate locally where possible:

- current/trailing/forward yield
- annual dividend
- 1/3/5/10-year dividend growth
- dividend increases/cuts
- years paying/growing
- payout ratio
- FCF coverage
- debt
- earnings growth
- ROE/ROA
- industry averages/medians/percentiles
- valuation versus industry
- Dividend Quality Score

The Dividend Quality Score is informational, not objective investment advice.

### Data integrity

- Never invent missing dividend dates.
- Represent missing source data as NULL/unknown.
- Distinguish ACTUAL, EXPECTED, ESTIMATED, and UNKNOWN dividend event status.
- Keep source/fetched timestamps.
- Keep data freshness visible in API responses.
- Use stable IDs and exchange+ticker uniqueness.

### yfinance efficiency

Avoid unnecessary calls:

- Do not call `Ticker.info` for every security.
- Prefer discovery/screener/query mechanisms where appropriate.
- Batch supported operations.
- Cache retrieved data.
- Use per-data-type TTLs.
- Incrementally update historical prices.
- Calculate analytics locally.
- Calculate competitors locally.
- Never fetch Yahoo data on normal page loads.

### Project structure

```text
dividend-explorer/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── api/
│   ├── web/
│   ├── db/
│   ├── yahoo/
│   ├── sync/
│   ├── analytics/
│   └── services/
├── data/
├── migrations/
├── tests/
├── scripts/
├── docs/
├── .opencode/
├── pyproject.toml
├── .env
├── .gitignore
└── README.md
```

### Development principles

- Keep modules small and testable.
- Keep yfinance behind a provider/client abstraction.
- Keep business logic out of route handlers.
- Keep database access in repositories/services.
- Use typed Pydantic schemas for API contracts.
- Add tests for queue state transitions, retry/backoff, analytics, change detection, and API endpoints.
- Prefer simple synchronous code unless concurrency is demonstrably useful.
- Preserve SQLite compatibility.
- Make configuration environment-driven.
- Do not silently fabricate financial data.

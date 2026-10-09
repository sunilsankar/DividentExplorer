# AGENTS.md — Dividend Explorer

## Mission

Build and maintain Dividend Explorer according to `docs/architecture.md`.

## Non-negotiable architecture

- SQLite is the operational source of truth.
- yfinance/Yahoo Finance is an ingestion provider only.
- Web and API routes never fetch Yahoo data directly.
- Use a persistent SQLite job queue for V1.
- Use a separate Python sync worker.
- No Docker, Celery, Redis, RabbitMQ, PostgreSQL, Kubernetes, or microservices in V1.

## Data ingestion rules

- Keep all Yahoo/yfinance code under `app/yahoo/`.
- Prefer the smallest data request that satisfies a job.
- Cache and reuse existing data.
- Respect configurable rate limits and delays.
- Use retry/backoff for transient failures.
- Pause or defer work when upstream throttling occurs.
- Never implement anti-bot evasion such as proxy rotation, fingerprint spoofing, CAPTCHA bypass, or similar mechanisms.
- Missing source data must remain missing; never invent values.

## API rules

- All public application APIs live under `/api/v1`.
- APIs are read-only in V1.
- API routes read from application services/SQLite.
- API requests must never initiate Yahoo requests.
- Maintain stable response schemas.
- Include data freshness metadata.
- Use pagination for collections.
- Keep OpenAPI documentation accurate.

## UI rules

- Use Jinja2 + HTMX + lightweight CSS.
- Do not add a frontend framework unless explicitly requested.
- Sync dashboard should use polling rather than WebSockets in V1.

## Database rules

- Use SQLAlchemy models/repositories.
- Use Alembic migrations for schema changes.
- Preserve SQLite WAL mode and foreign keys.
- Avoid database-specific features that prevent future PostgreSQL migration unless necessary.

## Testing

Before considering a feature complete:

1. Add unit tests for core business logic.
2. Add API tests for new endpoints.
3. Test SQLite persistence.
4. Test worker restart/resume behavior where relevant.
5. Test missing/null source data.
6. Test retry/backoff state transitions.
7. Run the project's test suite.

## Coding style

- Python 3.12+.
- Type hints for public functions and service boundaries.
- Clear names over clever abstractions.
- Small functions.
- Explicit error handling.
- Avoid unnecessary dependencies.
- Keep configuration in environment/config modules.

## Implementation order

Prefer this sequence:

1. Configuration and database foundation.
2. SQLAlchemy models and Alembic.
3. Repositories/services.
4. Persistent sync queue.
5. yfinance provider abstraction.
6. Worker and rate limiter.
7. Discovery/company synchronization.
8. Dividend synchronization.
9. Price/financial synchronization.
10. Analytics and change detection.
11. REST API.
12. Web UI.
13. Sync dashboard.
14. Competitor calculations.
15. Integration and end-to-end tests.

# Dividend Explorer

A lightweight dividend-stock discovery, tracking, and analytics application built with Python 3.12+, FastAPI, SQLAlchemy, SQLite (WAL mode), Jinja2, HTMX, and Chart.js.

SQLite is the operational source of truth. Yahoo Finance/yfinance is an ingestion provider only; web and API routes never fetch Yahoo data directly.

---

## Prerequisites

- **Python**: 3.12 or newer
- **Virtual Environment**: Recommended

---

## Quick Start: How to Run Locally

### 1. Set Up Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

Install the project in editable mode:

```bash
pip install -e .
```

### 3. Configure Environment (Optional)

Copy the default environment configuration:

```bash
cp .env.example .env
```

Defaults:
- `DATABASE_URL`: `sqlite:///data/dividend-explorer.db`
- `REQUEST_DELAY_SECONDS`: `1.0`
- `THROTTLE_PAUSE_SECONDS`: `60.0`
- `WORKER_POLL_INTERVAL`: `5.0`

### 4. Initialize Database

Run Alembic schema migrations:

```bash
alembic upgrade head
```

---

## Running the Application

You can explore the application immediately using **Option A (Seed Demo Data)** or **Option B (Live Yahoo Finance Sync)**.

### Option A: Quick Preview with Demo Data (Recommended for first run)

Populate SQLite with realistic sample companies (JNJ, PG, KO, PEP, MSFT, AAPL), dividend histories, prices, and metrics:

```bash
python scripts/seed_demo_data.py
```

Then start the web server:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

---

### Option B: Live Data with Background Sync Worker

Start the web server:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal window, start the persistent sync worker:

```bash
source .venv/bin/activate
python -m app.sync.worker
```

The worker continuously polls the persistent SQLite queue, respects rate limits, handles upstream throttling backoff, and computes local dividend metrics.

#### Worker Options

```bash
# Process a single pending job and exit
python -m app.sync.worker --once

# Drain all pending jobs in the queue and exit
python -m app.sync.worker --drain

# Custom poll interval (seconds)
python -m app.sync.worker --interval 2.0
```

#### Triggering Ingestion from the UI

1. Navigate to **Sync Telemetry** at [http://localhost:8000/sync](http://localhost:8000/sync).
2. Enter a stock ticker (e.g. `JNJ`, `AAPL`, `O`) in the **Enqueue Stock Sync** card.
3. Or go to [http://localhost:8000/sync/exchanges](http://localhost:8000/sync/exchanges) and click **Enqueue Full Sync** for NYSE or NASDAQ.
4. The worker will process the discovery, company profile, dividends, prices, financials, and local analytics pipeline asynchronously.

---

## Web UI & API Endpoints

### Web Interface (HTML + HTMX + Chart.js)

- **Market Overview / Dashboard**: [http://localhost:8000/](http://localhost:8000/)
- **Stock Screener & Search**: [http://localhost:8000/stocks](http://localhost:8000/stocks)
- **Stock Detail & Charts**: [http://localhost:8000/stocks/JNJ](http://localhost:8000/stocks/JNJ)
- **Industry & Sector Analytics**: [http://localhost:8000/industries](http://localhost:8000/industries)
- **Competitor Comparison**: [http://localhost:8000/competitors?ticker=KO](http://localhost:8000/competitors?ticker=KO)
- **Dividend Calendar**: [http://localhost:8000/calendar](http://localhost:8000/calendar)
- **Analytics & Leaders**: [http://localhost:8000/analytics](http://localhost:8000/analytics)
- **Sync Telemetry & Queue**: [http://localhost:8000/sync](http://localhost:8000/sync)
- **Exchange Sync Status**: [http://localhost:8000/sync/exchanges](http://localhost:8000/sync/exchanges)
- **Change Audit Log**: [http://localhost:8000/changes](http://localhost:8000/changes)

### REST API (`/api/v1`) & Documentation

All API endpoints are read-only and return data freshness metadata:

- **Interactive OpenAPI (Swagger) UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Alternative ReDoc UI**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI JSON Spec**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

Core API endpoints:
- `GET /api/v1/companies` (supports `search`, `sector`, `industry`, `sort_by`, `page`, `page_size`)
- `GET /api/v1/companies/{ticker}`
- `GET /api/v1/dividends?ticker={ticker}`
- `GET /api/v1/dividend-metrics/{ticker}`
- `GET /api/v1/prices/{ticker}`
- `GET /api/v1/financials/{ticker}`
- `GET /api/v1/industries`
- `GET /api/v1/competitors/{ticker}`
- `GET /api/v1/analytics/quality-leaders`
- `GET /api/v1/sync/status`

---

## SQLite Backup and Restore

Create a consistent backup while the application and sync worker are running:

```bash
python -m app.db.backup backup \
  --database data/dividend-explorer.db \
  --output backups/dividend-explorer.db
```

To restore from a backup (stop the web server and worker first):

```bash
python -m app.db.backup restore \
  --input backups/dividend-explorer.db \
  --database data/dividend-explorer.db
```

The backup utility uses SQLite's native online backup API (`sqlite3.Connection.backup`), validates integrity via `PRAGMA integrity_check`, and atomically replaces the destination.

---

## Production Deployment

Dividend Explorer follows a native single-server deployment model (no Docker or microservices in V1). Two processes run under `systemd`: the FastAPI web application and the background sync worker. The server syncs updates directly from GitHub.

### 1. Server Setup & Dependencies (One-Time Bootstrap)

```bash
# Clone repository
git clone https://github.com/sunilsankar/DividentExplorer.git /opt/dividend-explorer
cd /opt/dividend-explorer

# Create virtual environment and install package
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Configure environment and run migrations
# Note: .env and data/ are gitignored and reside only on this server
cp .env.example .env
alembic upgrade head
```

### 2. Systemd Service Configuration

Create the web service at `/etc/systemd/system/dividend-web.service`:

```ini
[Unit]
Description=Dividend Explorer Web Application
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/dividend-explorer
EnvironmentFile=/opt/dividend-explorer/.env
ExecStart=/opt/dividend-explorer/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Create the background worker service at `/etc/systemd/system/dividend-worker.service`:

```ini
[Unit]
Description=Dividend Explorer Ingestion Worker
After=network.target dividend-web.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/dividend-explorer
EnvironmentFile=/opt/dividend-explorer/.env
ExecStart=/opt/dividend-explorer/.venv/bin/python -m app.sync.worker
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start both services:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dividend-web dividend-worker
```

### 3. Access & Reverse Proxy

**LAN / Local Access (Default)**:
No reverse proxy is needed. For LAN access, adjust `--host 0.0.0.0` in `dividend-web.service` or use an SSH tunnel from your client:
```bash
ssh -L 8000:localhost:8000 user@server-ip
# Then open http://localhost:8000 on your local machine
```

**Public Exposure (Optional)**:
If exposing publicly with a domain:

- **Caddy** (automatic HTTPS):
  ```caddyfile
  dividend.yourdomain.com {
      reverse_proxy 127.0.0.1:8000
  }
  ```

- **Nginx**:
  ```nginx
  server {
      listen 80;
      server_name dividend.yourdomain.com;

      location / {
          proxy_pass http://127.0.0.1:8000;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
      }
  }
  ```

### 4. Automated Backup Schedule

Add a daily cron job using the online backup tool:

```bash
# Add to crontab (crontab -e)
0 2 * * * /opt/dividend-explorer/.venv/bin/python -m app.db.backup backup --database /opt/dividend-explorer/data/dividend-explorer.db --output /var/backups/dividend-explorer-$(date +\%F).db
```

### 5. Application Updates (One-Command Deploy via Git)

Whenever you push code changes from your development machine to GitHub, deploy them on the server with a single command:

```bash
cd /opt/dividend-explorer
./scripts/deploy.sh
```

The deploy script automatically:
1. `git pull --ff-only` — safely pulls fast-forward commits from GitHub without accidental merge commits.
2. Updates dependencies via `.venv/bin/pip install -e .`.
3. Safely stops `dividend-web` and `dividend-worker` so SQLite DDL schema updates can acquire an exclusive lock without blocking or crashing running workers.
4. Runs `alembic upgrade head` to apply any new database migrations.
5. Starts `dividend-worker` and `dividend-web` back up and prints their status.

---

## Running the Test Suite

Run the full automated test suite (64 unit, integration, and view tests):

```bash
python3 -m unittest discover -s tests -v
```

---

## Project Structure

```text
dividend-explorer/
├── app/
│   ├── main.py              # FastAPI application & lifespan management
│   ├── config.py            # Environment configuration
│   ├── api/                 # Versioned REST API schemas & endpoints (/api/v1)
│   ├── web/                 # Jinja2 templates, HTMX views, static assets
│   ├── db/                  # SQLite models, repositories, session, backup tool
│   ├── yahoo/               # Ingestion client abstraction & sanitizers
│   ├── sync/                # Persistent queue, rate limiter, handlers, worker
│   ├── analytics/           # Local dividend math & quality scoring
│   └── services/            # Domain services for stock & sync coordination
├── data/                    # Operational SQLite database (git-ignored)
├── migrations/              # Alembic migration scripts
├── scripts/
│   └── seed_demo_data.py    # Idempotent demo data generator
├── tests/                   # 14 test modules covering all subsystems
├── docs/                    # Architecture documentation
├── pyproject.toml           # Project metadata and dependencies
└── README.md
```

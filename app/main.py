"""Main FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.config import get_settings
from app.db.models import Base
from app.db.repositories import ExchangeRepository
from app.db.session import engine, SessionLocal
from app.web.views import router as web_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure data directory
    settings = get_settings()
    settings.ensure_data_dir()

    # Ensure tables exist for SQLite operational database
    Base.metadata.create_all(bind=engine)

    # Seed default exchanges if none exist
    with SessionLocal() as db:
        repo = ExchangeRepository(db)
        repo.get_or_create(code="NYSE", name="New York Stock Exchange", country="USA", timezone="America/New_York", currency="USD")
        repo.get_or_create(code="NASDAQ", name="NASDAQ Stock Market", country="USA", timezone="America/New_York", currency="USD")
        repo.get_or_create(code="ARCA", name="NYSE Arca (ETFs)", country="USA", timezone="America/New_York", currency="USD")
        repo.get_or_create(code="AMS", name="Euronext Amsterdam", country="Netherlands", timezone="Europe/Amsterdam", currency="EUR")
        repo.get_or_create(code="PAR", name="Euronext Paris", country="France", timezone="Europe/Paris", currency="EUR")
        repo.get_or_create(code="FRA", name="XETRA / Frankfurt", country="Germany", timezone="Europe/Berlin", currency="EUR")
        repo.get_or_create(code="BIT", name="Borsa Italiana", country="Italy", timezone="Europe/Rome", currency="EUR")
        repo.get_or_create(code="LSE", name="London Stock Exchange", country="UK", timezone="Europe/London", currency="GBP")
        db.commit()

    yield


app = FastAPI(
    title="Dividend Explorer",
    description="Dividend analytics, tracking, and synchronization platform using SQLite and Yahoo Finance",
    version="1.0.0",
    lifespan=lifespan,
)

# Static files
static_dir = Path(__file__).parent / "web" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Mount routers
app.include_router(api_router)
app.include_router(web_router)


@app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
def favicon():
    ico_path = Path(__file__).parent / "web" / "static" / "img" / "favicon.ico"
    if ico_path.exists():
        return FileResponse(ico_path, media_type="image/x-icon")
    svg_path = Path(__file__).parent / "web" / "static" / "img" / "logo.svg"
    return FileResponse(svg_path, media_type="image/svg+xml")


@app.get("/health", tags=["system"])
def health_check():
    return {"status": "ok"}

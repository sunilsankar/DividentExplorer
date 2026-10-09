import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///data/dividend-explorer.db")
    request_delay_seconds: float = float(os.getenv("REQUEST_DELAY_SECONDS", "1.0"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))

    @property
    def sqlite_path(self) -> Path | None:
        if self.database_url.startswith("sqlite:///"):
            path = Path(self.database_url.removeprefix("sqlite:///"))
            return path
        return None

    def ensure_data_dir(self) -> None:
        if path := self.sqlite_path:
            path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()


def get_settings() -> Settings:
    return settings

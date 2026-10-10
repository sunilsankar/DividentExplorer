import logging
import threading
from typing import Optional

from app.config import get_settings
from app.db.session import SessionLocal
from app.services.sync_service import SyncService

logger = logging.getLogger(__name__)


class AutoCleanupRunner:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        settings = get_settings()
        if not settings.auto_cleanup_enabled:
            logger.info("Auto-cleanup is disabled (AUTO_CLEANUP_ENABLED=false)")
            return

        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="auto-cleanup-worker",
        )
        self._thread.start()
        logger.info(
            "Auto-cleanup runner started (interval: %sm, grace: %sh)",
            settings.auto_cleanup_interval_minutes,
            settings.auto_cleanup_grace_hours,
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            logger.info("Auto-cleanup runner stopped")

    def _run(self) -> None:
        settings = get_settings()
        interval_seconds = max(settings.auto_cleanup_interval_minutes * 60, 60)
        # ponytail: initial 30s delay on startup to let app finish initial boots and syncs
        if self._stop_event.wait(timeout=30.0):
            return

        while not self._stop_event.is_set():
            try:
                with SessionLocal() as db:
                    service = SyncService(db)
                    deleted = service.cleanup_unclassified(grace_hours=settings.auto_cleanup_grace_hours)
                    if deleted > 0:
                        logger.info("Auto-cleanup removed %d unclassified stocks", deleted)
            except Exception as e:
                logger.error("Auto-cleanup encountered error: %s", e)

            if self._stop_event.wait(timeout=interval_seconds):
                break


_runner: Optional[AutoCleanupRunner] = None


def get_auto_cleanup_runner() -> AutoCleanupRunner:
    global _runner
    if _runner is None:
        _runner = AutoCleanupRunner()
    return _runner

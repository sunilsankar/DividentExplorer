import logging
import os
import signal
import sys
import time
from typing import Optional

from app.config import settings
from app.db.session import SessionLocal
from app.sync.handlers import dispatch_job
from app.sync.queue import SyncQueue, SyncRunManager, WorkerHeartbeatManager
from app.sync.rate_limiter import RateLimiter
from app.yahoo.client import UpstreamThrottledError, YahooClient

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("dividend_sync_worker")


class SyncWorker:
    """Standalone background sync worker executing jobs from persistent SQLite queue."""

    def __init__(
        self,
        worker_id: Optional[str] = None,
        poll_interval: float = 2.0,
        request_delay: Optional[float] = None,
        yahoo_client: Optional[YahooClient] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        self.worker_id = worker_id or f"worker-{os.getpid()}"
        self.poll_interval = poll_interval
        self.running = False
        self.queue = SyncQueue(default_max_attempts=settings.max_retries)
        self.run_mgr = SyncRunManager()
        self.rate_limiter = rate_limiter or RateLimiter(
            base_delay_seconds=request_delay if request_delay is not None else settings.request_delay_seconds,
            jitter_ratio=0.2,
        )
        self.yahoo = yahoo_client or YahooClient()

    def stop(self) -> None:
        logger.info("Worker stop requested")
        self.running = False

    def run_once(self) -> bool:
        """Processes a single pending job if available. Returns True if a job was processed."""
        with SessionLocal() as session:
            # Reclaim stale jobs from crashed workers
            self.queue.reap_stale_jobs(session)
            WorkerHeartbeatManager.heartbeat(session, worker_id=self.worker_id, status="IDLE")

            # Check if rate limiter is currently paused due to upstream throttling
            if self.rate_limiter.is_paused:
                logger.info(
                    "Throttling active: pausing worker for %.1fs",
                    self.rate_limiter.remaining_pause,
                )
                time.sleep(min(self.poll_interval, self.rate_limiter.remaining_pause))
                return False

            job = self.queue.acquire_next(session)
            if not job:
                return False

            logger.info("Acquired job #%d: type=%s ticker=%s", job.id, job.job_type, job.ticker)
            WorkerHeartbeatManager.heartbeat(session, worker_id=self.worker_id, status="BUSY", current_job_id=job.id)

            run = self.run_mgr.start_run(
                session=session,
                run_type=job.job_type,
                target_ticker=job.ticker,
                worker_id=self.worker_id,
            )
            session.commit()

            try:
                result_msg = dispatch_job(
                    job=job,
                    session=session,
                    yahoo=self.yahoo,
                    rate_limiter=self.rate_limiter,
                    queue=self.queue,
                )
                self.queue.complete(session, job.id, message=result_msg)
                self.run_mgr.finish_run(session, run.id, status="SUCCESS", items_processed=1)
                session.commit()
                logger.info("Completed job #%d: %s", job.id, result_msg)
            except UpstreamThrottledError as ute:
                logger.warning(
                    "Upstream throttled on job #%d: %s. Pausing for %.1fs",
                    job.id,
                    ute,
                    ute.pause_seconds,
                )
                self.rate_limiter.pause(ute.pause_seconds)
                self.queue.fail_and_retry(
                    session,
                    job.id,
                    error_message=str(ute),
                    backoff_seconds=ute.pause_seconds,
                )
                self.run_mgr.finish_run(session, run.id, status="FAILED", error_message=str(ute))
                session.commit()
            except Exception as exc:
                logger.exception("Failed job #%d: %s", job.id, exc)
                self.queue.fail_and_retry(session, job.id, error_message=str(exc))
                self.run_mgr.finish_run(session, run.id, status="FAILED", error_message=str(exc))
                session.commit()

            return True

    def run_forever(self) -> None:
        self.running = True
        logger.info("Starting sync worker [%s]", self.worker_id)

        def _signal_handler(signum, frame):
            logger.info("Received signal %s; shutting down cleanly", signum)
            self.stop()

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        while self.running:
            processed = self.run_once()
            if not processed and self.running:
                time.sleep(self.poll_interval)

        with SessionLocal() as session:
            WorkerHeartbeatManager.heartbeat(session, worker_id=self.worker_id, status="STOPPED")
        logger.info("Worker stopped successfully")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Dividend Explorer Sync Worker")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit")
    parser.add_argument("--drain", action="store_true", help="Drain queue until empty and exit")
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    args = parser.parse_args()

    settings.ensure_data_dir()
    worker = SyncWorker(poll_interval=args.interval)
    if args.once:
        worker.run_once()
    elif args.drain:
        while worker.run_once():
            pass
    else:
        worker.run_forever()


if __name__ == "__main__":
    main()

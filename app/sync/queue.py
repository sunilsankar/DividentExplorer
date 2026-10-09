from datetime import datetime, timedelta
import random
from typing import Any, Optional, Sequence
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import SyncJob, SyncRun, WorkerStatus, utcnow


class SyncQueue:
    """Persistent SQLite-backed sync job queue."""

    def __init__(self, default_max_attempts: int = 3, default_priority: int = 10) -> None:
        self.default_max_attempts = default_max_attempts
        self.default_priority = default_priority

    def enqueue(
        self,
        session: Session,
        job_type: str,
        ticker: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        priority: Optional[int] = None,
        max_attempts: Optional[int] = None,
        run_at: Optional[datetime] = None,
        deduplicate: bool = True,
        parent_job_id: Optional[int] = None,
    ) -> SyncJob:
        ticker_norm = ticker.upper().strip() if ticker else None
        if deduplicate:
            stmt = select(SyncJob).where(
                SyncJob.job_type == job_type,
                SyncJob.status.in_(["PENDING", "RUNNING", "RETRY"]),
            )
            if ticker_norm:
                stmt = stmt.where(SyncJob.ticker == ticker_norm)
            if entity_type:
                stmt = stmt.where(SyncJob.entity_type == entity_type)
            if entity_id is not None:
                stmt = stmt.where(SyncJob.entity_id == entity_id)

            existing = session.execute(stmt).scalars().first()
            if existing:
                return existing

        job = SyncJob(
            job_type=job_type,
            ticker=ticker_norm,
            entity_type=entity_type,
            entity_id=entity_id,
            parent_job_id=parent_job_id,
            priority=priority if priority is not None else self.default_priority,
            status="PENDING",
            attempts=0,
            max_attempts=max_attempts if max_attempts is not None else self.default_max_attempts,
            next_run_at=run_at or utcnow(),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(job)
        session.flush()
        return job

    def enqueue_batch(
        self,
        session: Session,
        job_type: str,
        tickers: Sequence[str],
        priority: Optional[int] = None,
        deduplicate: bool = True,
    ) -> list[SyncJob]:
        jobs: list[SyncJob] = []
        for ticker in tickers:
            job = self.enqueue(
                session=session,
                job_type=job_type,
                ticker=ticker,
                priority=priority,
                deduplicate=deduplicate,
            )
            jobs.append(job)
        return jobs

    def acquire_next_job(
        self,
        session: Session,
        worker_id: str,
        randomize: bool = True,
    ) -> Optional[SyncJob]:
        """Claim the next available pending/retry job atomically."""
        now = utcnow()
        stmt = select(SyncJob.id).where(
            SyncJob.status.in_(["PENDING", "RETRY"]),
            or_(SyncJob.next_run_at.is_(None), SyncJob.next_run_at <= now),
        )

        if randomize:
            # Randomize order across matching priority tier to smooth ingestion traffic
            stmt = stmt.order_by(SyncJob.priority.desc(), func.random())
        else:
            stmt = stmt.order_by(SyncJob.priority.desc(), SyncJob.created_at.asc())

        # ponytail: SQLite optimistic claim with randomized order smoothing; ceiling is single SQLite writer throughput, upgrade to SELECT FOR UPDATE SKIP LOCKED if moving to PostgreSQL
        candidate_id = session.execute(stmt.limit(1)).scalar_one_or_none()
        if candidate_id is None:
            return None

        # Lock and claim candidate
        job = session.get(SyncJob, candidate_id)
        if not job or job.status not in ["PENDING", "RETRY"]:
            # Raced or no longer eligible
            return None

        job.status = "RUNNING"
        job.locked_at = now
        job.locked_by = worker_id
        job.attempts += 1
        job.updated_at = now
        session.flush()
        return job

    def acquire_next(
        self,
        session: Session,
        worker_id: str = "worker",
        randomize: bool = True,
    ) -> Optional[SyncJob]:
        return self.acquire_next_job(session=session, worker_id=worker_id, randomize=randomize)

    def complete_job(self, session: Session, job_id: int) -> Optional[SyncJob]:
        job = session.get(SyncJob, job_id)
        if not job:
            return None

        job.status = "COMPLETED"
        job.locked_at = None
        job.locked_by = None
        job.error = None
        job.updated_at = utcnow()
        session.flush()
        return job

    def complete(self, session: Session, job_id: int, message: Optional[str] = None) -> Optional[SyncJob]:
        return self.complete_job(session, job_id)

    def fail_job(
        self,
        session: Session,
        job_id: int,
        error: str,
        backoff_base_seconds: float = 10.0,
        backoff_factor: float = 2.0,
        max_backoff_seconds: float = 1800.0,
        jitter: bool = True,
    ) -> Optional[SyncJob]:
        job = session.get(SyncJob, job_id)
        if not job:
            return None

        now = utcnow()
        job.error = error
        job.locked_at = None
        job.locked_by = None
        job.updated_at = now

        if job.attempts < job.max_attempts:
            # Exponential backoff with jitter
            # attempts is 1 for 1st failure -> delay = base * factor^0 = base
            delay = backoff_base_seconds * (backoff_factor ** max(0, job.attempts - 1))
            delay = min(delay, max_backoff_seconds)
            if jitter:
                # Add 0% - 25% jitter
                delay += random.uniform(0.0, delay * 0.25)

            job.status = "RETRY"
            job.next_run_at = now + timedelta(seconds=delay)
        else:
            job.status = "FAILED"

        session.flush()
        return job

    def fail_and_retry(
        self,
        session: Session,
        job_id: int,
        error_message: str,
        backoff_seconds: Optional[float] = None,
    ) -> Optional[SyncJob]:
        if backoff_seconds is not None:
            return self.fail_job(session, job_id, error=error_message, backoff_base_seconds=backoff_seconds, backoff_factor=1.0)
        return self.fail_job(session, job_id, error=error_message)

    def cancel_job(self, session: Session, job_id: int) -> Optional[SyncJob]:
        job = session.get(SyncJob, job_id)
        if not job:
            return None
        job.status = "CANCELLED"
        job.locked_at = None
        job.locked_by = None
        job.updated_at = utcnow()
        session.flush()
        return job

    def reap_stale_jobs(
        self,
        session: Session,
        stale_timeout_seconds: int = 300,
    ) -> int:
        """Reset jobs stuck in RUNNING due to ungraceful worker termination or crash."""
        now = utcnow()
        stale_threshold = now - timedelta(seconds=stale_timeout_seconds)

        stmt = select(SyncJob).where(
            SyncJob.status == "RUNNING",
            SyncJob.locked_at < stale_threshold,
        )
        stale_jobs = session.execute(stmt).scalars().all()
        reaped_count = 0

        for job in stale_jobs:
            reaped_count += 1
            job.locked_at = None
            job.locked_by = None
            job.updated_at = now
            if job.attempts < job.max_attempts:
                job.status = "RETRY"
                job.next_run_at = now
                job.error = f"Reaped after stale lock (> {stale_timeout_seconds}s)"
            else:
                job.status = "FAILED"
                job.error = f"Failed after exceeding max attempts via stale lock"

        if reaped_count > 0:
            session.flush()

        return reaped_count

    def get_job(self, session: Session, job_id: int) -> Optional[SyncJob]:
        return session.get(SyncJob, job_id)

    def retry_all_failed(self, session: Session, job_type: Optional[str] = None) -> int:
        stmt = select(SyncJob).where(SyncJob.status == "FAILED")
        if job_type:
            stmt = stmt.where(SyncJob.job_type == job_type)
        failed_jobs = session.execute(stmt).scalars().all()
        count = 0
        now = utcnow()
        for job in failed_jobs:
            job.status = "PENDING"
            job.attempts = 0
            job.error = None
            job.next_run_at = now
            job.updated_at = now
            count += 1
        if count > 0:
            session.flush()
        return count

    def get_stats(self, session: Session) -> dict[str, int]:
        stmt = select(SyncJob.status, func.count(SyncJob.id)).group_by(SyncJob.status)
        rows = session.execute(stmt).all()
        stats = {
            "PENDING": 0,
            "RUNNING": 0,
            "RETRY": 0,
            "COMPLETED": 0,
            "FAILED": 0,
            "CANCELLED": 0,
            "TOTAL": 0,
        }
        total = 0
        for status, count in rows:
            stats[status] = count
            total += count
        stats["TOTAL"] = total
        # Lowercase aliases
        stats["pending_jobs"] = stats["PENDING"]
        stats["running_jobs"] = stats["RUNNING"]
        stats["retry_jobs"] = stats["RETRY"]
        stats["completed_jobs"] = stats["COMPLETED"]
        stats["failed_jobs"] = stats["FAILED"]
        stats["cancelled_jobs"] = stats["CANCELLED"]
        stats["total_jobs"] = stats["TOTAL"]
        stats["pending"] = stats["PENDING"]
        stats["running"] = stats["RUNNING"]
        stats["retry"] = stats["RETRY"]
        stats["completed"] = stats["COMPLETED"]
        stats["failed"] = stats["FAILED"]
        stats["cancelled"] = stats["CANCELLED"]
        stats["total"] = stats["TOTAL"]
        return stats


class SyncRunManager:
    """Manages high-level sync run lifecycle."""

    @staticmethod
    def start_run(
        session: Session,
        run_type: str,
        target_ticker: Optional[str] = None,
        worker_id: Optional[str] = None,
    ) -> SyncRun:
        run = SyncRun(
            run_type=run_type,
            status="RUNNING",
            started_at=utcnow(),
            items_processed=0,
            items_failed=0,
        )
        session.add(run)
        session.flush()
        return run

    @staticmethod
    def finish_run(
        session: Session,
        run_id: int,
        items_processed: int = 0,
        items_failed: int = 0,
        error: Optional[str] = None,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[SyncRun]:
        run = session.get(SyncRun, run_id)
        if not run:
            return None
        run.items_processed = items_processed
        run.items_failed = items_failed
        err = error or error_message
        run.error = err
        if status:
            run.status = status
        else:
            run.status = "FAILED" if err and items_processed == 0 else "COMPLETED"
        run.completed_at = utcnow()
        session.flush()
        return run


class WorkerHeartbeatManager:
    """Records and queries worker heartbeats and statuses."""

    @staticmethod
    def heartbeat(
        session: Session,
        worker_id: str,
        status: str = "IDLE",
        current_job_id: Optional[int] = None,
        meta_json: Optional[str] = None,
    ) -> WorkerStatus:
        stmt = select(WorkerStatus).where(WorkerStatus.worker_id == worker_id)
        worker = session.execute(stmt).scalar_one_or_none()
        now = utcnow()
        if worker:
            worker.status = status
            worker.current_job_id = current_job_id
            worker.heartbeat_at = now
            if meta_json is not None:
                worker.meta_json = meta_json
        else:
            worker = WorkerStatus(
                worker_id=worker_id,
                status=status,
                current_job_id=current_job_id,
                heartbeat_at=now,
                meta_json=meta_json,
            )
            session.add(worker)
        session.flush()
        return worker

    @staticmethod
    def get_active_workers(
        session: Session,
        timeout_seconds: int = 60,
    ) -> Sequence[WorkerStatus]:
        threshold = utcnow() - timedelta(seconds=timeout_seconds)
        stmt = (
            select(WorkerStatus)
            .where(WorkerStatus.heartbeat_at >= threshold)
            .order_by(WorkerStatus.heartbeat_at.desc())
        )
        return session.execute(stmt).scalars().all()

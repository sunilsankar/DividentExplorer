from typing import Any, Dict, Optional, Sequence
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import DataChange, SyncJob, SyncRun, WorkerStatus
from app.db.repositories import ChangeRepository, ExchangeRepository
from app.sync.queue import SyncQueue, SyncRunManager, WorkerHeartbeatManager


class SyncService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.queue = SyncQueue()
        self.change_repo = ChangeRepository(session)
        self.exchange_repo = ExchangeRepository(session)

    def get_queue_stats(self) -> dict[str, int]:
        return self.queue.get_stats(self.session)

    def get_recent_jobs(self, limit: int = 50, status: Optional[str] = None) -> Sequence[SyncJob]:
        stmt = select(SyncJob)
        if status:
            stmt = stmt.where(SyncJob.status == status)
        stmt = stmt.order_by(desc(SyncJob.updated_at)).limit(limit)
        return self.session.execute(stmt).scalars().all()

    def get_recent_runs(self, limit: int = 20) -> Sequence[SyncRun]:
        stmt = select(SyncRun).order_by(desc(SyncRun.started_at)).limit(limit)
        return self.session.execute(stmt).scalars().all()

    def get_active_workers(self, timeout_seconds: int = 60) -> Sequence[WorkerStatus]:
        return WorkerHeartbeatManager.get_active_workers(self.session, timeout_seconds=timeout_seconds)

    def get_recent_changes(
        self,
        limit: int = 50,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
    ) -> Sequence[DataChange]:
        return self.change_repo.list_recent(limit=limit, entity_type=entity_type, entity_id=entity_id)

    def enqueue_ticker_sync(self, ticker: str, priority: int = 5) -> SyncJob:
        job = self.queue.enqueue(
            session=self.session,
            job_type="SYNC_COMPANY",
            ticker=ticker,
            priority=priority,
        )
        self.session.commit()
        return job

    # ponytail: priority 4 ensures worker drains company (8) and sub-jobs (7) before next exchange discovery
    def enqueue_exchange_sync(self, exchange_code: str, priority: int = 4) -> SyncJob:
        job = self.queue.enqueue(
            session=self.session,
            job_type="SYNC_EXCHANGE",
            ticker=exchange_code.upper(),
            priority=priority,
        )
        self.session.commit()
        return job

    def retry_all_failed(self) -> int:
        retried = self.queue.retry_all_failed(self.session)
        self.session.commit()
        return retried

    def get_exchange_progress(self, exchange_code: str) -> Dict[str, Any]:
        """Calculates progress of the most recent exchange sync job and its children."""
        from sqlalchemy import select, func
        code = exchange_code.strip().upper()
        root_job = (
            self.session.execute(
                select(SyncJob)
                .where(SyncJob.job_type == "SYNC_EXCHANGE", SyncJob.ticker == code)
                .order_by(SyncJob.id.desc())
            )
            .scalars()
            .first()
        )
        if not root_job:
            return {
                "status": "IDLE",
                "percent": 0.0,
                "total": 0,
                "completed": 0,
                "failed": 0,
                "pending": 0,
                "last_synced_at": None,
            }

        status_counts = dict(
            self.session.execute(
                select(SyncJob.status, func.count(SyncJob.id))
                .where(SyncJob.parent_job_id == root_job.id)
                .group_by(SyncJob.status)
            ).all()
        )
        completed = status_counts.get("COMPLETED", 0)
        failed = status_counts.get("FAILED", 0)
        pending = status_counts.get("PENDING", 0) + status_counts.get("RUNNING", 0) + status_counts.get("RETRY", 0)
        total = completed + failed + pending

        if total == 0:
            percent = 100.0 if root_job.status == "COMPLETED" else 0.0
        else:
            percent = round(((completed + failed) / total) * 100, 1)

        if root_job.status == "PENDING" and total == 0:
            job_status = "PENDING"
        elif root_job.status in ("PENDING", "RUNNING") or pending > 0:
            job_status = "RUNNING"
        elif root_job.status == "FAILED" or (failed > 0 and completed == 0):
            job_status = "FAILED"
        else:
            job_status = "COMPLETED"

        last_synced_at = root_job.updated_at if root_job.status == "COMPLETED" else None

        return {
            "root_job_id": root_job.id,
            "status": job_status,
            "percent": percent,
            "total": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "last_synced_at": last_synced_at,
        }

    # Aliases for convenience
    get_queue_status = get_queue_stats
    enqueue_company_sync = enqueue_ticker_sync

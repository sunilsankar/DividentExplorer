from datetime import timedelta
from typing import Any, Dict, Optional, Sequence
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.models import DataChange, SyncJob, SyncRun, WorkerStatus, utcnow
from app.db.repositories import ChangeRepository, CompanyRepository, ExchangeRepository
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
    def enqueue_exchange_sync(
        self,
        exchange_code: str,
        priority: int = 4,
        deduplicate: bool = True,
    ) -> tuple[SyncJob, bool]:
        code = exchange_code.upper().strip()
        if deduplicate:
            existing = self.session.execute(
                select(SyncJob).where(
                    SyncJob.job_type == "SYNC_EXCHANGE",
                    SyncJob.ticker == code,
                    SyncJob.status.in_(["PENDING", "RUNNING", "RETRY"]),
                )
            ).scalars().first()
            if existing:
                return existing, True

        job = self.queue.enqueue(
            session=self.session,
            job_type="SYNC_EXCHANGE",
            ticker=code,
            priority=priority,
            deduplicate=deduplicate,
        )
        self.session.commit()
        return job, False

    def cancel_in_flight_exchange_syncs(self, exchange_code: str) -> int:
        code = exchange_code.upper().strip()
        jobs = self.session.execute(
            select(SyncJob).where(
                SyncJob.job_type == "SYNC_EXCHANGE",
                SyncJob.ticker == code,
                SyncJob.status.in_(["PENDING", "RUNNING", "RETRY"]),
            )
        ).scalars().all()
        count = 0
        for j in jobs:
            self.queue.cancel_job(self.session, j.id)
            count += 1
        self.session.commit()
        return count

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

    def get_stuck_running_count(self, threshold_seconds: int = 300) -> int:
        threshold = utcnow() - timedelta(seconds=threshold_seconds)
        stmt = select(func.count(SyncJob.id)).where(
            SyncJob.status == "RUNNING",
            SyncJob.locked_at < threshold,
        )
        return int(self.session.execute(stmt).scalar_one())

    # ponytail: sequential exchange progress queries; ceiling is 8-10 seeded exchanges, upgrade to joined rollup if exchanges grow to hundreds
    def get_all_exchange_progress(self) -> list[dict[str, Any]]:
        comp_repo = CompanyRepository(self.session)
        rows: list[dict[str, Any]] = []
        for ex in self.exchange_repo.list_all():
            progress = self.get_exchange_progress(ex.code)
            rows.append({
                "code": ex.code,
                "name": ex.name,
                "country": ex.country,
                "currency": ex.currency,
                "is_active": ex.is_active,
                "companies_count": len(comp_repo.list_by_exchange(ex.id)),
                "progress": progress,
                "status": progress["status"],
                "percent": progress["percent"],
                "total": progress["total"],
                "completed": progress["completed"],
                "failed": progress["failed"],
                "last_synced_at": progress.get("last_synced_at"),
            })
        return rows

    # Aliases for convenience
    get_queue_status = get_queue_stats
    enqueue_company_sync = enqueue_ticker_sync

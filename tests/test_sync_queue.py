from datetime import datetime, timedelta, timezone
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, SyncJob, utcnow
from app.sync.queue import SyncQueue, SyncRunManager, WorkerHeartbeatManager


class SyncQueueTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.session: Session = self.session_factory()
        self.queue = SyncQueue(default_max_attempts=3, default_priority=10)

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_enqueue_and_deduplicate(self) -> None:
        job1 = self.queue.enqueue(
            self.session,
            job_type="SYNC_COMPANY",
            ticker="AAPL",
            priority=10,
        )
        self.session.commit()
        self.assertIsNotNone(job1.id)
        self.assertEqual(job1.status, "PENDING")

        # Duplicate enqueue should return existing job
        job2 = self.queue.enqueue(
            self.session,
            job_type="SYNC_COMPANY",
            ticker="AAPL",
        )
        self.assertEqual(job1.id, job2.id)

    def test_acquire_and_complete_job(self) -> None:
        self.queue.enqueue(self.session, job_type="SYNC_COMPANY", ticker="MSFT", priority=20)
        self.queue.enqueue(self.session, job_type="SYNC_COMPANY", ticker="GOOGL", priority=10)
        self.session.commit()

        # Highest priority should be acquired first
        claimed = self.queue.acquire_next_job(self.session, worker_id="worker-1", randomize=False)
        self.session.commit()
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.ticker, "MSFT")
        self.assertEqual(claimed.status, "RUNNING")
        self.assertEqual(claimed.attempts, 1)
        self.assertEqual(claimed.locked_by, "worker-1")

        # Complete the job
        completed = self.queue.complete_job(self.session, claimed.id)
        self.session.commit()
        self.assertIsNotNone(completed)
        self.assertEqual(completed.status, "COMPLETED")
        self.assertIsNone(completed.locked_by)

    def test_fail_job_exponential_backoff_and_exhaustion(self) -> None:
        job = self.queue.enqueue(self.session, job_type="SYNC_COMPANY", ticker="FAIL_TEST", max_attempts=2)
        self.session.commit()

        claimed = self.queue.acquire_next_job(self.session, worker_id="worker-1")
        self.session.commit()
        self.assertEqual(claimed.attempts, 1)

        # First failure: should transition to RETRY with backoff
        retried = self.queue.fail_job(
            self.session,
            claimed.id,
            error="Connection timeout",
            backoff_base_seconds=10.0,
            jitter=False,
        )
        self.session.commit()
        self.assertEqual(retried.status, "RETRY")
        self.assertGreater(retried.next_run_at, utcnow())

        # Simulate time passing so next_run_at is now eligible
        retried.next_run_at = utcnow() - timedelta(seconds=1)
        self.session.commit()

        claimed2 = self.queue.acquire_next_job(self.session, worker_id="worker-1")
        self.session.commit()
        self.assertIsNotNone(claimed2)
        self.assertEqual(claimed2.attempts, 2)

        # Second failure: max_attempts=2 reached -> FAILED
        failed = self.queue.fail_job(self.session, claimed2.id, error="Fatal API error")
        self.session.commit()
        self.assertEqual(failed.status, "FAILED")
        self.assertEqual(failed.error, "Fatal API error")

    def test_reap_stale_jobs(self) -> None:
        job = self.queue.enqueue(self.session, job_type="SYNC_COMPANY", ticker="STALE_TICKER")
        self.session.commit()

        claimed = self.queue.acquire_next_job(self.session, worker_id="crashed-worker")
        # Fake stale locked_at 10 minutes ago
        claimed.locked_at = utcnow() - timedelta(minutes=10)
        self.session.commit()

        reaped = self.queue.reap_stale_jobs(self.session, stale_timeout_seconds=300)
        self.session.commit()
        self.assertEqual(reaped, 1)

        reloaded = self.session.get(SyncJob, claimed.id)
        self.assertEqual(reloaded.status, "RETRY")
        self.assertIsNone(reloaded.locked_by)

    def test_retry_all_failed(self) -> None:
        job = self.queue.enqueue(self.session, job_type="SYNC_COMPANY", ticker="TICKER_X")
        job.status = "FAILED"
        job.attempts = 3
        job.error = "Some error"
        self.session.commit()

        count = self.queue.retry_all_failed(self.session)
        self.session.commit()
        self.assertEqual(count, 1)

        reloaded = self.session.get(SyncJob, job.id)
        self.assertEqual(reloaded.status, "PENDING")
        self.assertEqual(reloaded.attempts, 0)
        self.assertIsNone(reloaded.error)

    def test_queue_stats(self) -> None:
        self.queue.enqueue(self.session, job_type="SYNC_COMPANY", ticker="AAA")
        self.queue.enqueue(self.session, job_type="SYNC_COMPANY", ticker="BBB")
        self.session.commit()

        stats = self.queue.get_stats(self.session)
        self.assertEqual(stats["PENDING"], 2)
        self.assertEqual(stats["TOTAL"], 2)

    def test_sync_run_and_worker_heartbeat(self) -> None:
        run = SyncRunManager.start_run(self.session, run_type="FULL_DISCOVERY")
        self.session.commit()
        self.assertEqual(run.status, "RUNNING")

        finished = SyncRunManager.finish_run(
            self.session,
            run_id=run.id,
            items_processed=100,
            items_failed=2,
        )
        self.session.commit()
        self.assertEqual(finished.status, "COMPLETED")
        self.assertEqual(finished.items_processed, 100)

        # Worker heartbeat
        worker = WorkerHeartbeatManager.heartbeat(
            self.session,
            worker_id="worker-node-1",
            status="SYNCING",
        )
        self.session.commit()
        self.assertEqual(worker.status, "SYNCING")

        active = WorkerHeartbeatManager.get_active_workers(self.session, timeout_seconds=60)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].worker_id, "worker-node-1")

    def test_enqueue_dedups_within_same_parent(self) -> None:
        p = self.queue.enqueue(self.session, "SYNC_EXCHANGE", ticker="US")
        self.session.flush()
        j1 = self.queue.enqueue(self.session, "SYNC_COMPANY", ticker="AAPL", parent_job_id=p.id)
        j2 = self.queue.enqueue(self.session, "SYNC_COMPANY", ticker="AAPL", parent_job_id=p.id)
        self.assertEqual(j1.id, j2.id)

    def test_enqueue_allows_different_parents(self) -> None:
        p1 = self.queue.enqueue(self.session, "SYNC_EXCHANGE", ticker="US")
        p2 = self.queue.enqueue(self.session, "SYNC_EXCHANGE", ticker="EU")
        self.session.flush()
        j1 = self.queue.enqueue(self.session, "SYNC_COMPANY", ticker="AAPL", parent_job_id=p1.id)
        j2 = self.queue.enqueue(self.session, "SYNC_COMPANY", ticker="AAPL", parent_job_id=p2.id)
        self.assertNotEqual(j1.id, j2.id)

    def test_enqueue_legacy_global_dedup_when_no_parent(self) -> None:
        j1 = self.queue.enqueue(self.session, "SYNC_COMPANY", ticker="AAPL")
        self.session.flush()
        j2 = self.queue.enqueue(self.session, "SYNC_COMPANY", ticker="AAPL")
        self.assertEqual(j1.id, j2.id)

    def test_enqueue_dedup_false_always_inserts(self) -> None:
        j1 = self.queue.enqueue(self.session, "SYNC_COMPANY", ticker="AAPL", deduplicate=False)
        self.session.flush()
        j2 = self.queue.enqueue(self.session, "SYNC_COMPANY", ticker="AAPL", deduplicate=False)
        self.assertNotEqual(j1.id, j2.id)


if __name__ == "__main__":
    unittest.main()

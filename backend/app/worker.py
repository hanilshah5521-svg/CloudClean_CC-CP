"""CloudClean's background worker: `python -m app.worker` (from backend/).

Runs queued jobs one at a time — analysis, video compression, large
restores, rule evaluation — and queues each user's auto-compression rule run
once a day. One worker on one small VM is the intended deployment; job
claiming is atomic, so a second worker would never run the same job, but it
would also compete for the same CPU and disk.

    python -m app.worker            # run until Ctrl+C / SIGTERM
    python -m app.worker --once     # run what's queued now, then exit
"""
from __future__ import annotations

import argparse
import logging
import signal
import threading
import time

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.models import WorkerHeartbeat
from app.services import job_service, optimization_service, rules_service
from app.utils import workdir

logger = logging.getLogger("cloudclean.worker")

HEARTBEAT_SECONDS = 10
SCHEDULE_CHECK_SECONDS = 60
ORIGINALS_CHECK_SECONDS = 600


class Worker:
    def __init__(self, poll_seconds: float | None = None):
        self.poll_seconds = settings.worker_poll_seconds if poll_seconds is None else poll_seconds
        self.id = job_service.worker_id()
        self._stop = threading.Event()
        self._last_schedule_check = 0.0
        self._last_originals_check = 0.0

    def stop(self, *_):
        if self._stop.is_set():
            raise KeyboardInterrupt  # second Ctrl+C: don't wait for the job
        logger.info("Stopping after the current job (press Ctrl+C again to abort it)…")
        self._stop.set()

    def startup(self) -> None:
        init_db()
        with SessionLocal() as db:
            if job_service.worker_online(db, exclude=self.id):
                # Another worker is alive: its running job and scratch files are not ours to clean up.
                logger.warning("Another worker is running; skipping interrupted-job recovery.")
            else:
                failed = job_service.recover_interrupted(db)
                removed = workdir.remove_leftovers()
                if failed or removed:
                    logger.info("Marked %d interrupted job(s) failed; removed %d leftover temp dir(s).", failed, removed)
            job_service.beat(db, self.id)

    def run_pending(self) -> int:
        """Run queued jobs until the queue is empty (or stop is requested)."""
        ran = 0
        while not self._stop.is_set():
            with SessionLocal() as db:
                job_id = job_service.claim_next_job(db)
            if job_id is None:
                break
            logger.info("Running job %s", job_id)
            job_service.run_job(job_id, claimed=True)
            ran += 1
        return ran

    def schedule_rules(self) -> None:
        if time.monotonic() - self._last_schedule_check < SCHEDULE_CHECK_SECONDS:
            return
        self._last_schedule_check = time.monotonic()
        with SessionLocal() as db:
            queued = rules_service.schedule_due_evaluations(db)
        if queued:
            logger.info("Queued the nightly rule evaluation for %d user(s).", queued)

    def delete_expired_originals(self) -> None:
        """Compressed files keep their original for KEEP_ORIGINAL_DAYS (for
        Undo); after that, delete it so the storage is actually freed."""
        if time.monotonic() - self._last_originals_check < ORIGINALS_CHECK_SECONDS:
            return
        self._last_originals_check = time.monotonic()
        with SessionLocal() as db:
            deleted = optimization_service.delete_expired_originals(db)
        if deleted:
            logger.info("Deleted %d kept original version(s) whose undo window ended.", deleted)

    def _heartbeat_loop(self) -> None:
        # Separate thread: a 20-minute video job must not look like a dead worker.
        while not self._stop.wait(HEARTBEAT_SECONDS):
            try:
                with SessionLocal() as db:
                    job_service.beat(db, self.id)
            except Exception:
                logger.exception("Heartbeat failed")

    def forever(self) -> None:
        self.startup()
        threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True).start()
        logger.info("Worker %s started (polling every %ss).", self.id, self.poll_seconds)
        try:
            while not self._stop.is_set():
                try:
                    self.schedule_rules()
                    self.delete_expired_originals()
                    self.run_pending()
                except Exception:  # e.g. the database briefly locked — keep the worker alive
                    logger.exception("Worker loop error")
                self._stop.wait(self.poll_seconds)
        finally:
            self._stop.set()
            self.remove_heartbeat()
            logger.info("Worker stopped.")

    def remove_heartbeat(self) -> None:
        with SessionLocal() as db:
            row = db.get(WorkerHeartbeat, self.id)
            if row:
                db.delete(row)
                db.commit()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.worker", description="CloudClean background worker")
    parser.add_argument("--once", action="store_true", help="run the jobs queued now (and due rules), then exit")
    parser.add_argument("--poll", type=float, default=None, help="seconds between queue checks")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    worker = Worker(args.poll)
    signal.signal(signal.SIGINT, worker.stop)
    signal.signal(signal.SIGTERM, worker.stop)
    if args.once:
        worker.startup()
        try:
            worker.schedule_rules()
            logger.info("Ran %d job(s).", worker.run_pending())
        finally:
            worker.remove_heartbeat()
        return
    worker.forever()


if __name__ == "__main__":
    main()

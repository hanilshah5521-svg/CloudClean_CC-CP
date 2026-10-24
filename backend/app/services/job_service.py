"""Background jobs: a queue kept in the database (no Celery, no Redis — it has
to run on one small free-tier VM next to SQLite). The API enqueues a Job row;
the worker process (`python -m app.worker`) claims it, runs it and records
progress on the row, which the frontend polls.

- Claiming is a single atomic `UPDATE jobs SET status='running' WHERE id=?
  AND status='queued'`: only one claimer can win, so a job never runs twice.
- Demo Mode jobs only simulate (no downloads, no ffmpeg), so they run inline
  in the request that creates them: Demo Mode works without the worker.
- A job interrupted by a worker crash/restart is marked failed when the
  worker next starts, never silently retried (it may have half-uploaded).
"""
from __future__ import annotations

import logging
import os
import socket
import time
from datetime import datetime, timedelta, timezone

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Job, OptimizationAction, RuleSuggestion, User, WorkerHeartbeat

logger = logging.getLogger("cloudclean")

ACTIVE_STATUSES = ("queued", "running")
HEARTBEAT_STALE_AFTER = timedelta(seconds=30)
INTERRUPTED = "Interrupted: the background worker stopped while this job was running."


def utcnow() -> datetime:
    """Naive UTC — what SQLite DateTime columns store and return."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------------ enqueue

def active_job(db: Session, user: User, kind: str, target: str = "") -> Job | None:
    return db.query(Job).filter(
        Job.user_id == user.id, Job.kind == kind, Job.target == target, Job.status.in_(ACTIVE_STATUSES),
    ).order_by(Job.id.desc()).first()


def create_job(db: Session, user: User, kind: str, payload: dict | None = None, target: str = "") -> Job:
    job = Job(user_id=user.id, kind=kind, target=target, payload=payload or {}, status="queued",
              message="Waiting for the background worker…")
    db.add(job)
    db.commit()
    return job


def submit_job(db: Session, user: User, kind: str, payload: dict | None = None, target: str = "") -> Job:
    """Queue a job — or return the same work if it's already queued or
    running. Demo Mode jobs run right away, inside this call."""
    existing = active_job(db, user, kind, target)
    if existing:
        return existing
    job = create_job(db, user, kind, payload, target)
    if user.is_demo:
        run_job(job.id)
        db.refresh(job)
    return job


# ------------------------------------------------------------------ claim

def claim_job(db: Session, job_id: int) -> bool:
    now = utcnow()
    claimed = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == "queued")
        .values(status="running", started_at=now, updated_at=now, message="Starting…")
    ).rowcount
    db.commit()
    return claimed == 1


def claim_next_job(db: Session) -> int | None:
    """Oldest queued job, claimed atomically; None when the queue is empty."""
    while True:
        row = db.query(Job.id).filter(Job.status == "queued").order_by(Job.id).first()
        if row is None:
            return None
        if claim_job(db, row.id):
            return row.id
        # Someone else claimed it between the SELECT and the UPDATE — try the next one.


# ------------------------------------------------------------------ run

class Progress:
    """progress(percent, message) for job handlers. Writes to the job row at
    most once a second (plus big jumps), so a fast ffmpeg progress stream
    doesn't hammer SQLite.

    It commits the job's session, so handlers call it only between steps —
    never while they hold changes they might still want to roll back."""

    def __init__(self, db: Session, job: Job, min_interval: float = 1.0):
        self.db, self.job, self.min_interval = db, job, min_interval
        self._last_write = 0.0
        self._percent = job.progress or 0  # kept here: the row is expired after every commit

    def __call__(self, percent: float, message: str = "") -> None:
        percent = max(0, min(99, int(percent)))  # 100 only once the job has really finished
        now = time.monotonic()
        if now - self._last_write < self.min_interval and percent - self._percent < 10:
            return
        self._last_write = now
        self._percent = max(self._percent, percent)
        self.job.progress = self._percent
        if message:
            self.job.message = message[:255]
        self.job.updated_at = utcnow()
        self.db.commit()

    def scaled(self, start: float, end: float):
        """A progress callable mapping a sub-step's 0-100 onto start..end."""
        return lambda percent, message="": self(start + (end - start) * percent / 100, message)


def run_job(job_id: int, *, claimed: bool = False) -> None:
    """Run one job in its own session, recording the result or the error on
    the job row. Never raises: a failing job must not take the worker down."""
    from app.services.job_handlers import HANDLERS  # handlers import the services, which import this module

    with SessionLocal() as db:
        if not claimed and not claim_job(db, job_id):
            return  # already claimed elsewhere
        job = db.get(Job, job_id)
        user = db.get(User, job.user_id)
        try:
            if user is None:
                raise LookupError("The account this job belonged to no longer exists.")
            handler = HANDLERS.get(job.kind)
            if handler is None:
                raise LookupError(f"Unknown job kind {job.kind!r}.")
            result = handler(db, user, dict(job.payload or {}), Progress(db, job))
        except Exception as exc:  # noqa: BLE001 — recorded on the job, see error_message()
            db.rollback()
            message = error_message(exc)
            job = db.get(Job, job_id)
            _finish(job, "failed", error=message)
            _settle_suggestion(db, job, None, message)
            db.commit()
            return
        _finish(job, "done", result=result)
        _settle_suggestion(db, job, result, "")
        db.commit()


def _finish(job: Job, status: str, result: dict | None = None, error: str = "") -> None:
    now = utcnow()
    job.status = status
    job.result = result
    job.error = error
    job.message = "Done" if status == "done" else "Failed"
    if status == "done":
        job.progress = 100
    job.finished_at = job.updated_at = now


def error_message(exc: Exception) -> str:
    from app.services.optimization_service import OptimizationError

    if isinstance(exc, (OptimizationError, LookupError)):
        return str(exc)
    if isinstance(exc, (PermissionError, RefreshError)):
        return "Google authorization expired or was revoked. Please reconnect your Google account."
    if isinstance(exc, HttpError):
        return f"Google API error ({exc.resp.status}): {exc.reason}."
    logger.exception("Job failed")
    return "Something went wrong while running this job; the details are in the worker's log."


def _settle_suggestion(db: Session, job: Job, result: dict | None, error: str) -> None:
    """A job started from a rule suggestion closes that suggestion."""
    suggestion_id = (job.payload or {}).get("suggestion_id")
    suggestion = db.get(RuleSuggestion, suggestion_id) if suggestion_id else None
    if suggestion is None or suggestion.user_id != job.user_id:
        return
    if result is None:
        suggestion.status, suggestion.detail = "failed", error
    else:
        suggestion.status = "applied" if result.get("success") else "skipped"
        suggestion.detail = result.get("message", "")


# ------------------------------------------------------------------ worker housekeeping

def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def beat(db: Session, wid: str) -> None:
    row = db.get(WorkerHeartbeat, wid)
    if row is None:
        db.add(WorkerHeartbeat(worker_id=wid, last_seen=utcnow()))
    else:
        row.last_seen = utcnow()
    db.commit()


def worker_online(db: Session, exclude: str = "") -> bool:
    return db.query(WorkerHeartbeat).filter(
        WorkerHeartbeat.last_seen >= utcnow() - HEARTBEAT_STALE_AFTER, WorkerHeartbeat.worker_id != exclude,
    ).first() is not None


def recover_interrupted(db: Session) -> int:
    """Run at worker start (when no other worker is alive): whatever was
    'running' was cut off by a crash or restart. Fail it — retrying
    automatically could repeat a half-finished upload — and leave a note on
    any History entry it was in the middle of."""
    jobs = db.query(Job).filter(Job.status == "running").all()
    for job in jobs:
        _finish(job, "failed", error=INTERRUPTED + " Start it again if it's still needed.")
        _settle_suggestion(db, job, None, INTERRUPTED)
    for action in db.query(OptimizationAction).filter(OptimizationAction.status == "in_progress"):
        action.status = "failed"
        action.detail = (f"{INTERRUPTED} If Drive shows a newer version of this file, the original is revision "
                         f"{action.revision_id} under Manage versions in Drive.")
    db.commit()
    return len(jobs)

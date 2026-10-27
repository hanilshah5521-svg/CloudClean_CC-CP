from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Job, User
from app.schemas import JobOut
from app.security.session import get_current_user
from app.services.job_service import ACTIVE_STATUSES, worker_online

router = APIRouter(prefix="/api", tags=["jobs"])


def job_out(db: Session, job: Job, user: User) -> dict:
    out = JobOut.model_validate(job).model_dump(mode="json")
    # Demo jobs never need the worker (they run inline).
    out["worker_online"] = user.is_demo or job.status not in ACTIVE_STATUSES or worker_online(db)
    return out


@router.get("/jobs/{job_id}")
def get_job(job_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Jobs of any linked account (a "scan all accounts" polls each of them).
    from app.services.account_service import linked_users

    owners = {u.id: u for u in linked_users(db, user)}
    job = db.query(Job).filter(Job.id == job_id, Job.user_id.in_(list(owners))).first()
    if not job:  # someone else's job looks exactly like a missing one
        raise HTTPException(status_code=404, detail="Job not found.")
    return job_out(db, job, owners[job.user_id])


@router.get("/jobs")
def list_jobs(active: bool = False, kind: str = "", limit: int = Query(20, ge=1, le=100),
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Job).filter(Job.user_id == user.id)
    if active:
        q = q.filter(Job.status.in_(ACTIVE_STATUSES))
    if kind:
        q = q.filter(Job.kind == kind)
    return [job_out(db, j, user) for j in q.order_by(Job.id.desc()).limit(limit)]

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
    if user.id == job.user_id:  # the linked account the job runs in (and records History for)
        out["account_id"], out["account_email"] = user.id, user.email
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
              all_accounts: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """This account's jobs, or (all_accounts) every linked account's — History
    covers them all, so an Undo running in another account shows its progress."""
    from app.services.account_service import members_by_id

    owners = members_by_id(db, user) if all_accounts else {user.id: user}
    q = db.query(Job).filter(Job.user_id.in_(list(owners)))
    if active:
        q = q.filter(Job.status.in_(ACTIVE_STATUSES))
    if kind:
        q = q.filter(Job.kind == kind)
    return [job_out(db, j, owners[j.user_id]) for j in q.order_by(Job.id.desc()).limit(limit)]

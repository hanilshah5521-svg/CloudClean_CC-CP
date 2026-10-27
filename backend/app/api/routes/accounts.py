"""Linked Google accounts: list, switch, remove, scan all, and duplicates
spread across accounts. See app/services/account_service.py."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.routes.jobs import job_out
from app.core.config import settings
from app.core.database import get_db
from app.models import Job, User
from app.security.session import get_current_user
from app.services import account_service as svc
from app.services.job_service import ACTIVE_STATUSES, submit_job

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _run(fn, *args):
    try:
        return fn(*args)
    except svc.AccountError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_accounts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc.account_summary(db, user, settings.google_oauth_configured)


@router.post("/{account_id}/switch")
def switch_account(account_id: int, request: Request, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    try:
        target = svc.linked_user(db, user, account_id)
    except svc.AccountError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    request.session["user_id"] = target.id
    return {"ok": True, "active_id": target.id, "email": target.email}


@router.delete("/{account_id}")
def remove_account(account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        target = svc.linked_user(db, user, account_id)
    except svc.AccountError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    email = target.email
    _run(svc.unlink, db, user, target)
    return {"ok": True, "removed": email}


@router.post("/simulated")
def add_simulated_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Demo Mode only: link another simulated account and scan it (inline, like every demo job)."""
    account = _run(svc.add_demo_account, db, user)
    submit_job(db, account, "analyze")
    return {"id": account.id, "email": account.email}


@router.post("/scan")
def scan_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Queue a Drive analysis for every linked account (one job each, run by
    the worker with that account's own token). Demo accounts finish inline."""
    out = []
    for member in svc.linked_users(db, user):
        job = submit_job(db, member, "analyze")
        out.append({"account_id": member.id, "email": member.email, "job": job_out(db, job, member)})
    return out


@router.get("/scan")
def active_scans(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Analyses still running for any linked account (to resume progress after a reload)."""
    members = {m.id: m for m in svc.linked_users(db, user)}
    jobs = db.query(Job).filter(Job.user_id.in_(list(members)), Job.kind == "analyze",
                                Job.status.in_(ACTIVE_STATUSES)).all()
    return [{"account_id": j.user_id, "email": members[j.user_id].email, "job": job_out(db, j, members[j.user_id])}
            for j in jobs]


@router.get("/duplicates")
def cross_duplicates(account_id: int | None = None, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    return svc.cross_account_duplicates(db, user, account_id)


class RemoveCopiesRequest(BaseModel):
    keep_file_id: int
    remove_file_ids: list[int]


@router.post("/duplicates/remove")
def remove_copies(body: RemoveCopiesRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"results": _run(svc.remove_copies, db, user, body.keep_file_id, body.remove_file_ids)}

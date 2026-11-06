from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.routes.jobs import job_out
from app.core.database import get_db
from app.models import OptimizationAction, User
from app.schemas import ActionHistoryOut
from app.security.session import get_current_user
from app.services.account_service import AccountError, members_by_id, owner_fields, scoped_members
from app.services.job_service import submit_job
from app.services.optimization_service import (
    OptimizationError, free_original_space, restore_action, restore_runs_in_background,
)

router = APIRouter(prefix="/api", tags=["history"])


def _members(db: Session, user: User, account_id: int | None) -> dict[int, User]:
    try:
        return scoped_members(db, user, account_id)
    except AccountError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/history", response_model=list[ActionHistoryOut])
def get_history(limit: int = Query(200, ge=1, le=1000), account_id: int | None = None,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """What CloudClean did in every linked account (or just account_id), newest
    first, each row naming its account. Rows live in the database, so they
    survive restarts and re-scans; nothing but removing the account deletes them."""
    members = _members(db, user, account_id)
    rows = (
        db.query(OptimizationAction)
        .filter(OptimizationAction.user_id.in_(list(members)))
        .order_by(OptimizationAction.created_at.desc(), OptimizationAction.id.desc())
        .limit(limit)
        .all()
    )
    return [{**ActionHistoryOut.model_validate(r).model_dump(), **owner_fields(members[r.user_id])} for r in rows]


@router.get("/history/summary")
def history_summary(account_id: int | None = None, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """All-time totals over the whole History (not just the rows a page shows):
    space saved by actions still in effect, per action type, per account and
    per day. Undone actions don't count; trashed files count once Trash empties."""
    members = _members(db, user, account_id)
    rows = (
        db.query(OptimizationAction)
        .filter(OptimizationAction.user_id.in_(list(members)))
        .order_by(OptimizationAction.created_at.asc(), OptimizationAction.id.asc())
        .all()
    )
    by_action: dict[str, dict] = defaultdict(lambda: {"count": 0, "saved_bytes": 0})
    by_account = {mid: {**owner_fields(m), "saved_bytes": 0, "actions": 0} for mid, m in members.items()}
    by_day: dict[str, int] = defaultdict(int)
    saved = pending_bytes = pending_count = 0
    for r in rows:
        by_account[r.user_id]["actions"] += 1
        if r.can_free_space:
            pending_bytes += r.original_size_bytes
            pending_count += 1
        if r.status != "success" or r.action == "restored":
            continue
        by_action[r.action]["count"] += 1
        by_action[r.action]["saved_bytes"] += r.saved_bytes
        by_account[r.user_id]["saved_bytes"] += r.saved_bytes
        by_day[r.created_at.date().isoformat()] += r.saved_bytes
        saved += r.saved_bytes

    timeline, running = [], 0
    for day in sorted(by_day):
        running += by_day[day]
        # Midday of that (UTC) day, as a naive timestamp like every other date the API returns.
        timeline.append({"date": f"{day}T12:00:00", "saved_bytes": by_day[day], "cumulative_bytes": running})
    return {
        "saved_bytes": saved,
        "actions": len(rows),
        "first_action_at": rows[0].created_at if rows else None,
        "pending_originals_bytes": pending_bytes,
        "pending_originals": pending_count,
        "by_action": dict(by_action),
        "by_account": list(by_account.values()),
        "timeline": timeline,
    }


def _owned_action(db: Session, user: User, action_id: int) -> tuple[OptimizationAction, User]:
    """The action and the linked account it ran in: Undo runs in that account,
    with its own Google permission, wherever the user is working."""
    members = members_by_id(db, user)
    action = db.query(OptimizationAction).filter(
        OptimizationAction.id == action_id, OptimizationAction.user_id.in_(list(members))
    ).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found.")
    return action, members[action.user_id]


@router.post("/history/{action_id}/restore")
def restore(action_id: int, response: Response, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    """Undo an action. Undoing a video (or other large) compression means
    re-downloading and re-uploading the original, so that's queued as a
    "restore" job: the response is then {"job_id": ..., "job": {...}}."""
    action, owner = _owned_action(db, user, action_id)
    if restore_runs_in_background(db, owner, action):
        job = submit_job(db, owner, "restore", {"action_id": action.id, "file_name": action.file_name},
                         target=str(action.id))
        response.status_code = 202
        return {"job_id": job.id, "job": job_out(db, job, owner), **owner_fields(owner),
                "message": "Restoring the original version in the background…"}
    try:
        return {**restore_action(db, owner, action), **owner_fields(owner)}
    except OptimizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/history/{action_id}/free-space")
def free_space(action_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a compressed file's kept original version now (permanent: no Undo after this)."""
    action, owner = _owned_action(db, user, action_id)
    try:
        return {**free_original_space(db, owner, action), **owner_fields(owner)}
    except OptimizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

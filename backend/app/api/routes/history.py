from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.routes.jobs import job_out
from app.core.database import get_db
from app.models import OptimizationAction, User
from app.schemas import ActionHistoryOut
from app.security.session import get_current_user
from app.services.job_service import submit_job
from app.services.optimization_service import (
    OptimizationError, free_original_space, restore_action, restore_runs_in_background,
)

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history", response_model=list[ActionHistoryOut])
def get_history(limit: int = 100, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(OptimizationAction)
        .filter(OptimizationAction.user_id == user.id)
        .order_by(OptimizationAction.created_at.desc())
        .limit(limit)
        .all()
    )


@router.post("/history/{action_id}/restore")
def restore(action_id: int, response: Response, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    """Undo an action. Undoing a video (or other large) compression means
    re-downloading and re-uploading the original, so that's queued as a
    "restore" job: the response is then {"job_id": ..., "job": {...}}."""
    action = db.query(OptimizationAction).filter(
        OptimizationAction.id == action_id, OptimizationAction.user_id == user.id
    ).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found.")
    if restore_runs_in_background(db, user, action):
        job = submit_job(db, user, "restore", {"action_id": action.id, "file_name": action.file_name},
                         target=str(action.id))
        response.status_code = 202
        return {"job_id": job.id, "job": job_out(db, job, user),
                "message": "Restoring the original version in the background…"}
    try:
        return restore_action(db, user, action)
    except OptimizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/history/{action_id}/free-space")
def free_space(action_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a compressed file's kept original version now (permanent: no Undo after this)."""
    action = db.query(OptimizationAction).filter(
        OptimizationAction.id == action_id, OptimizationAction.user_id == user.id
    ).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found.")
    try:
        return free_original_space(db, user, action)
    except OptimizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

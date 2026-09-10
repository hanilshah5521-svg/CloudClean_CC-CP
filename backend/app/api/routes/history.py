from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import OptimizationAction, User
from app.schemas import ActionHistoryOut
from app.security.session import get_current_user
from app.services.optimization_service import OptimizationError, restore_action

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
def restore(action_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    action = db.query(OptimizationAction).filter(
        OptimizationAction.id == action_id, OptimizationAction.user_id == user.id
    ).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found.")
    try:
        return restore_action(db, user, action)
    except OptimizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

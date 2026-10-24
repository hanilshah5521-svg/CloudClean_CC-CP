from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import User
from app.security.session import get_current_user
from app.services import organize_service as svc

router = APIRouter(prefix="/api/organize", tags=["organize"])


class ApplyRequest(BaseModel):
    folder_name: str | None = Field(None, max_length=svc.MAX_FOLDER_NAME)


@router.get("")
def suggestions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc.list_suggestions(db, user)


@router.post("/{suggestion_id}/apply")
def apply(suggestion_id: int, body: ApplyRequest | None = None, user: User = Depends(get_current_user),
          db: Session = Depends(get_db)):
    try:
        return svc.apply_suggestion(db, user, suggestion_id, body.folder_name if body else None)
    except svc.OrganizeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{suggestion_id}/dismiss")
def dismiss(suggestion_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        svc.dismiss(db, user, suggestion_id)
    except svc.OrganizeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import OrganizeSuggestion, User
from app.security.session import get_current_user
from app.services import organize_service as svc
from app.services.account_service import members_by_id, owner_fields

router = APIRouter(prefix="/api/organize", tags=["organize"])


class ApplyRequest(BaseModel):
    folder_name: str | None = Field(None, max_length=svc.MAX_FOLDER_NAME)


def _owner(db: Session, user: User, suggestion_id: int) -> User:
    """The linked account a suggestion belongs to (the folder is made, and the
    files moved, in that account). Unknown ids fall through to the service's
    "no longer available" error."""
    members = members_by_id(db, user)
    row = db.query(OrganizeSuggestion.user_id).filter(
        OrganizeSuggestion.id == suggestion_id, OrganizeSuggestion.user_id.in_(list(members))).first()
    return members[row.user_id] if row else user


@router.get("")
def suggestions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Suggestions for every linked account, each labelled with its account."""
    out = []
    for member in members_by_id(db, user).values():
        out += [{**s, **owner_fields(member)} for s in svc.list_suggestions(db, member)]
    return sorted(out, key=lambda s: s["count"], reverse=True)


@router.post("/{suggestion_id}/apply")
def apply(suggestion_id: int, body: ApplyRequest | None = None, user: User = Depends(get_current_user),
          db: Session = Depends(get_db)):
    owner = _owner(db, user, suggestion_id)
    try:
        return {**svc.apply_suggestion(db, owner, suggestion_id, body.folder_name if body else None),
                **owner_fields(owner)}
    except svc.OrganizeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{suggestion_id}/dismiss")
def dismiss(suggestion_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        svc.dismiss(db, _owner(db, user, suggestion_id), suggestion_id)
    except svc.OrganizeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}

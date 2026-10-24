from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import GmailMessage, User
from app.security.session import get_current_user
from app.services.drive_service import gmail_access
from app.services.optimization_service import trash_gmail_messages

router = APIRouter(prefix="/api/gmail", tags=["gmail"])


class GmailTrashRequest(BaseModel):
    message_ids: list[int] = Field(min_length=1, max_length=500)


@router.get("")
def list_large_emails(
    older_than_days: int = Query(0, ge=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(GmailMessage).filter(GmailMessage.user_id == user.id, GmailMessage.is_trashed.is_(False))
    if older_than_days:
        q = q.filter(GmailMessage.inactivity_days >= older_than_days)
    total, total_bytes = q.with_entities(func.count(GmailMessage.id), func.sum(GmailMessage.size_bytes)).one()
    rows = q.order_by(GmailMessage.size_bytes.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "access": gmail_access(user),
        "min_mb": user.settings.gmail_min_mb,
        "total": total,
        "total_bytes": int(total_bytes or 0),
        "page": page,
        "page_size": page_size,
        "messages": [{
            "id": m.id, "subject": m.subject, "sender": m.sender, "received_time": m.received_time,
            "size_bytes": m.size_bytes, "has_attachment": m.has_attachment, "labels": m.labels,
            "inactivity_days": m.inactivity_days,
            # No /u/0/: the UI adds ?authuser=<email>, so the connected account opens, not the browser's default.
            "web_url": "" if user.is_demo else f"https://mail.google.com/mail/#all/{m.message_id}",
        } for m in rows],
    }


@router.post("/trash")
def trash_emails(body: GmailTrashRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if gmail_access(user) == "not_granted":
        raise HTTPException(status_code=403, detail="Gmail access wasn't granted. Reconnect your Google account and allow Gmail.")
    rows = db.query(GmailMessage).filter(GmailMessage.id.in_(body.message_ids), GmailMessage.user_id == user.id).all()
    if len(rows) != len(set(body.message_ids)):
        raise HTTPException(status_code=404, detail="One or more emails not found.")
    results = trash_gmail_messages(db, user, rows)
    return {"trashed": results}

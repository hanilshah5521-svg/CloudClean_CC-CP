"""Session-based auth. Uses Starlette's built-in signed-cookie
SessionMiddleware (itsdangerous under the hood) — no custom crypto, no JWT
library needed for a single-server local app. SameSite=Lax gives baseline
CSRF protection for free (cross-site POSTs don't carry the cookie)."""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated. Connect Google Drive or start Demo Mode first.")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Session expired. Please reconnect.")
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()

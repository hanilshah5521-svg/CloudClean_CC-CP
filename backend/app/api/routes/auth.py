import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.integrations.google_drive import build_auth_url, exchange_code, fetch_userinfo
from app.models import User, UserSettings
from app.schemas import UserOut
from app.security.session import get_current_user

router = APIRouter(tags=["auth"])


@router.get("/auth/google/url")
def google_auth_url():
    if not settings.google_oauth_configured:
        raise HTTPException(status_code=400, detail="Google OAuth is not configured on this server. Use Demo Mode, or set GOOGLE_CLIENT_ID/SECRET in .env.")
    url, state = build_auth_url()
    return {"url": url, "state": state}


@router.get("/auth/callback")
def google_callback(request: Request, code: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    if error:
        return RedirectResponse(f"{settings.frontend_url}/connect?error={error}")
    if not code:
        return RedirectResponse(f"{settings.frontend_url}/connect?error=missing_code")

    try:
        creds = exchange_code(code)
        info = fetch_userinfo(creds)
    except Exception:
        return RedirectResponse(f"{settings.frontend_url}/connect?error=oauth_failed")

    user = db.query(User).filter(User.google_id == info["id"]).first()
    if not user:
        user = User(google_id=info["id"], email=info.get("email", ""), name=info.get("name", ""),
                     picture_url=info.get("picture", ""), is_demo=False)
        db.add(user)
        db.flush()
        db.add(UserSettings(user_id=user.id))
    user.access_token = creds.token or ""
    user.refresh_token = creds.refresh_token or user.refresh_token or ""
    user.name = info.get("name", user.name)
    user.picture_url = info.get("picture", user.picture_url)
    db.commit()

    request.session["user_id"] = user.id
    return RedirectResponse(f"{settings.frontend_url}/dashboard")


@router.post("/auth/demo")
def start_demo(request: Request, db: Session = Depends(get_db)):
    user = User(email=f"demo-{uuid.uuid4().hex[:8]}@cloudclean.local", name="Demo User", is_demo=True)
    db.add(user)
    db.flush()
    db.add(UserSettings(user_id=user.id))
    db.commit()
    request.session["user_id"] = user.id
    return {"ok": True}


@router.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/api/user", response_model=UserOut)
def get_user(user: User = Depends(get_current_user)):
    return user

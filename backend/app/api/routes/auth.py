import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.integrations.google_drive import build_auth_url, exchange_code, fetch_userinfo
from app.models import User, UserSettings
from app.schemas import UserOut
from app.security.session import get_current_user
from app.services.account_service import delete_accounts, link as link_accounts

router = APIRouter(tags=["auth"])

DEMO_USER_TTL = timedelta(hours=24)


def _require_oauth():
    if not settings.google_oauth_configured:
        raise HTTPException(status_code=400, detail="Google OAuth is not configured on this server. Use Demo Mode, or set GOOGLE_CLIENT_ID/SECRET in .env.")


def _start_oauth(request: Request, choose_account: bool = False) -> str:
    url, state, code_verifier = build_auth_url(choose_account)
    # Both live in the signed session cookie: state is checked on callback
    # (stops a forged callback logging the victim into someone else's
    # account), and the PKCE verifier proves the code is redeemed by us.
    request.session["oauth_state"] = state
    request.session["oauth_code_verifier"] = code_verifier
    return url


@router.get("/auth/status")
def auth_status():
    """What sign-in options this server offers (no secrets): lets the Connect
    screen show a "not configured" banner instead of a dead button."""
    return {"google_configured": settings.google_oauth_configured, "gmail_enabled": settings.gmail_enabled}


@router.get("/auth/google/login")
def google_login(request: Request):
    """Browser navigates here directly; we remember state + PKCE verifier and redirect to Google."""
    if not settings.google_oauth_configured:
        # A page load, not an API call: send the user back with a readable message, not raw JSON.
        return _to_connect("not_configured")
    return RedirectResponse(_start_oauth(request))


@router.get("/auth/google/link")
def google_link(request: Request, user: User = Depends(get_current_user)):
    """"Add Google account": sign in to another Google account and link it to
    this profile. The account being worked in stays the same."""
    if user.is_demo:
        return RedirectResponse(f"{settings.frontend_url}/accounts?error=demo_link")
    if not settings.google_oauth_configured:
        return RedirectResponse(f"{settings.frontend_url}/accounts?error=not_configured")
    url = _start_oauth(request, choose_account=True)
    request.session["link_to_user_id"] = user.id
    return RedirectResponse(url)


@router.get("/auth/google/url")
def google_auth_url(request: Request):
    _require_oauth()
    return {"url": _start_oauth(request)}


def _to_connect(error: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.frontend_url}/connect?error={quote(error)}")


@router.get("/auth/callback")
def google_callback(request: Request, code: str | None = None, state: str | None = None,
                    error: str | None = None, db: Session = Depends(get_db)):
    expected_state = request.session.pop("oauth_state", None)
    code_verifier = request.session.pop("oauth_code_verifier", None)
    link_to = request.session.pop("link_to_user_id", None)
    linking_user = db.query(User).filter(User.id == link_to, User.is_demo.is_(False)).first() if link_to else None
    if error:
        if linking_user:  # cancelled while adding an account: stay signed in
            return RedirectResponse(f"{settings.frontend_url}/accounts?error={quote(error)}")
        return _to_connect(error)
    if not expected_state or not state or not secrets.compare_digest(state, expected_state):
        return _to_connect("state_mismatch")
    if not code:
        return _to_connect("missing_code")

    try:
        creds, granted_scopes = exchange_code(code, state, code_verifier or "")
        info = fetch_userinfo(creds)
    except Exception:
        return _to_connect("oauth_failed")

    user = db.query(User).filter(User.google_id == info["id"]).first()
    if not user:
        user = User(google_id=info["id"], email=info.get("email", ""), name=info.get("name", ""),
                    picture_url=info.get("picture", ""), is_demo=False)
        db.add(user)
        db.flush()
        db.add(UserSettings(user_id=user.id))
    user.access_token = creds.token or ""
    user.refresh_token = creds.refresh_token or user.refresh_token or ""
    user.token_expiry = creds.expiry
    user.granted_scopes = " ".join(granted_scopes)
    user.name = info.get("name", user.name)
    user.picture_url = info.get("picture", user.picture_url)
    db.commit()

    request.session.clear()  # new session on login (no fixation)
    if linking_user:
        link_accounts(db, linking_user, user)
        request.session["user_id"] = linking_user.id  # keep working in the same account
        return RedirectResponse(f"{settings.frontend_url}/accounts?linked={quote(user.email)}")
    request.session["user_id"] = user.id
    return RedirectResponse(f"{settings.frontend_url}/dashboard")


@router.post("/auth/demo")
def start_demo(request: Request, db: Session = Depends(get_db)):
    _purge_stale_demo_users(db)
    user = User(email=f"demo-{uuid.uuid4().hex[:8]}@cloudclean.local", name="Demo User", is_demo=True)
    db.add(user)
    db.flush()
    db.add(UserSettings(user_id=user.id))
    db.commit()
    request.session.clear()
    request.session["user_id"] = user.id
    return {"ok": True}


def _purge_stale_demo_users(db: Session):
    """Every "Try Demo Mode" click creates a user; drop ones older than a day
    so the database doesn't grow forever on a public deployment."""
    cutoff = (datetime.now(timezone.utc) - DEMO_USER_TTL).replace(tzinfo=None)
    stale = [uid for (uid,) in db.query(User.id).filter(User.is_demo.is_(True), User.created_at < cutoff)]
    if not stale:
        return
    delete_accounts(db, stale)


@router.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/api/user", response_model=UserOut)
def get_user(user: User = Depends(get_current_user)):
    return user

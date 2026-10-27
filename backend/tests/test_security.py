"""OAuth state/PKCE, token encryption and refresh persistence, secret key,
schema auto-migration and demo-user cleanup."""
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app.core.config import settings
from app.core.database import SessionLocal, _add_missing_columns, init_db
from app.integrations import google_drive
from app.main import app
from app.models import User, UserSettings

init_db()


def _configure_oauth(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "client-id")
    monkeypatch.setattr(settings, "google_client_secret", "client-secret")


def test_login_redirect_carries_state_and_pkce(monkeypatch):
    _configure_oauth(monkeypatch)
    client = TestClient(app)
    r = client.get("/auth/google/login", follow_redirects=False)
    assert r.status_code == 307
    query = parse_qs(urlparse(r.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"] and query["state"]
    assert "https://www.googleapis.com/auth/gmail.modify" in query["scope"][0]


def test_gmail_off_asks_for_drive_only_and_skips_gmail(monkeypatch):
    from app.services.drive_service import gmail_access

    _configure_oauth(monkeypatch)
    monkeypatch.setattr(settings, "gmail_enabled", False)
    r = TestClient(app).get("/auth/google/login", follow_redirects=False)
    scope = parse_qs(urlparse(r.headers["location"]).query)["scope"][0]
    assert "gmail" not in scope and "https://www.googleapis.com/auth/drive" in scope

    demo = TestClient(app)
    demo.post("/auth/demo")
    demo.post("/api/analyze")
    assert all(rec["type"] != "gmail" for rec in demo.get("/api/recommendations").json())
    with SessionLocal() as db:
        assert gmail_access(db.query(User).filter(User.is_demo.is_(True)).first()) == "disabled"


def test_login_without_oauth_config_returns_to_connect_page(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_client_secret", "")
    r = TestClient(app).get("/auth/google/login", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == f"{settings.frontend_url}/connect?error=not_configured"


def test_callback_rejects_missing_or_wrong_state(monkeypatch):
    _configure_oauth(monkeypatch)
    client = TestClient(app)
    r = client.get("/auth/callback", params={"code": "c", "state": "x"}, follow_redirects=False)
    assert r.headers["location"].endswith("/connect?error=state_mismatch")

    client.get("/auth/google/login", follow_redirects=False)  # session now holds the real state
    r = client.get("/auth/callback", params={"code": "c", "state": "forged"}, follow_redirects=False)
    assert r.headers["location"].endswith("/connect?error=state_mismatch")


def test_callback_exchanges_code_with_the_sessions_verifier(monkeypatch):
    _configure_oauth(monkeypatch)
    seen = {}

    class Creds:
        token, refresh_token, expiry = "access", "refresh", datetime(2030, 1, 1)

    def fake_exchange(code, state, verifier):
        seen.update(code=code, state=state, verifier=verifier)
        return Creds(), google_drive.BASE_SCOPES  # user unticked Gmail

    monkeypatch.setattr("app.api.routes.auth.exchange_code", fake_exchange)
    monkeypatch.setattr("app.api.routes.auth.fetch_userinfo", lambda creds: {"id": "g-123", "email": "u@example.com", "name": "U"})
    client = TestClient(app)
    login = client.get("/auth/google/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    r = client.get("/auth/callback", params={"code": "the-code", "state": state}, follow_redirects=False)
    assert r.headers["location"].endswith("/dashboard")
    assert seen["code"] == "the-code" and len(seen["verifier"]) >= 43
    assert client.get("/api/gmail").json()["access"] == "not_granted"


def test_tokens_are_encrypted_at_rest():
    with SessionLocal() as db:
        user = User(email="enc@example.com", name="E", access_token="ya29.plain-access", refresh_token="1//plain-refresh")
        db.add(user)
        db.commit()
        raw = db.execute(text("SELECT access_token, refresh_token FROM users WHERE id = :id"), {"id": user.id}).one()
        assert "plain" not in raw[0] and "plain" not in raw[1]
        db.expire_all()
        assert db.get(User, user.id).refresh_token == "1//plain-refresh"


def test_refreshed_access_token_is_persisted(monkeypatch):
    def fake_refresh(self, request):
        self.token = "fresh-token"
        self.expiry = datetime.utcnow() + timedelta(hours=1)

    monkeypatch.setattr(google_drive.Credentials, "refresh", fake_refresh)
    with SessionLocal() as db:
        user = User(email="refresh@example.com", name="R", access_token="stale", refresh_token="r",
                    token_expiry=datetime.utcnow() - timedelta(minutes=5))
        db.add(user)
        db.commit()
        google_drive.authorized_credentials(user)
        user_id = user.id
    with SessionLocal() as db:
        assert db.get(User, user_id).access_token == "fresh-token"


def test_no_hardcoded_secret_key():
    assert settings.resolved_secret_key == "test-secret-key"
    assert "dev-only-insecure" not in settings.resolved_secret_key


def test_old_databases_get_new_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE storage_snapshots (id INTEGER PRIMARY KEY, user_id INTEGER, used_bytes INTEGER)"))
        conn.execute(text("INSERT INTO storage_snapshots (user_id, used_bytes) VALUES (1, 5)"))
    _add_missing_columns(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("storage_snapshots")}
    assert {"drive_trash_bytes", "gmail_photos_bytes"} <= cols
    with engine.connect() as conn:
        assert conn.execute(text("SELECT drive_trash_bytes FROM storage_snapshots")).scalar() == 0


def test_stale_demo_users_are_purged():
    with SessionLocal() as db:
        old = User(email="old-demo@cloudclean.local", name="Demo", is_demo=True,
                   created_at=datetime.utcnow() - timedelta(days=3))
        db.add(old)
        db.flush()
        db.add(UserSettings(user_id=old.id))
        db.commit()
    r = TestClient(app).post("/auth/demo")
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        # (by email: SQLite may hand the freed id to the new demo user)
        assert db.query(User).filter_by(email="old-demo@cloudclean.local").first() is None

"""Central app configuration, loaded from environment variables (.env)."""
import secrets
from functools import cached_property
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
SECRET_KEY_FILE = DATA_DIR / ".secret_key"


class Settings(BaseSettings):
    # Looks for .env in the repo root first, then backend/.env — either works.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    # Google OAuth — left blank, app runs in Demo Mode until these are set.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/callback"
    # Also request Gmail access (gmail.modify) so large emails can be found
    # and trashed. Gmail shares the same 15 GB as Drive and Photos.
    gmail_enabled: bool = True

    # Signs session cookies and (unless TOKEN_ENCRYPTION_KEY is set) derives
    # the key that encrypts OAuth tokens at rest. Leave blank in development:
    # a random key is generated once and kept in data/.secret_key.
    secret_key: str = ""
    token_encryption_key: str = ""
    # Set true whenever the app is served over HTTPS (any real deployment),
    # so the session cookie is never sent over plain HTTP.
    cookie_secure: bool = False

    frontend_url: str = "http://localhost:5173"

    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'cloudclean.db'}"

    # Default analysis thresholds (overridable per-user in UserSettings).
    large_file_mb: int = 100
    very_large_file_mb: int = 500
    huge_file_mb: int = 1024
    inactive_days_default: int = 365

    # Background worker (`python -m app.worker`).
    worker_poll_seconds: float = 2.0
    # Auto-compression rules are evaluated once a day at this hour (UTC).
    # 21:00 UTC is 02:30 in India.
    rules_hour_utc: int = 21
    # Cap on jobs one nightly run starts by itself for auto-apply rules —
    # video re-encoding takes minutes per file on a small VM. The rest stay
    # pending and are picked up the next night.
    rules_max_auto_apply: int = 3

    # Video compression (ffmpeg). Blank paths = look on PATH (and, on
    # Windows, in winget's install folder).
    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    video_crf: int = 27
    video_preset: str = "medium"
    # Fewer threads = less RAM. 2 suits a 1 GB free-tier VM.
    video_threads: int = 2
    video_max_mb: int = 4096
    # Where videos are downloaded and re-encoded. Blank = the OS temp dir.
    job_temp_dir: str = ""

    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @cached_property
    def resolved_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        # Never fall back to a hard-coded key: anyone who read the source
        # could forge sessions. Generate one per installation instead.
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if SECRET_KEY_FILE.exists():
            return SECRET_KEY_FILE.read_text().strip()
        key = secrets.token_hex(32)
        SECRET_KEY_FILE.write_text(key)
        return key


settings = Settings()

"""Central app configuration, loaded from environment variables (.env)."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    # Looks for .env in the repo root first, then backend/.env — either works.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    # Google OAuth — left blank, app runs in Demo Mode until these are set.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/callback"

    secret_key: str = "dev-only-insecure-secret-change-me"
    frontend_url: str = "http://localhost:5173"

    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'cloudclean.db'}"

    # Default analysis thresholds (overridable per-user in UserSettings).
    large_file_mb: int = 100
    very_large_file_mb: int = 500
    huge_file_mb: int = 1024
    inactive_days_default: int = 365

    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


settings = Settings()

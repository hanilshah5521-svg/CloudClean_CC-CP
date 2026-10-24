"""Point the app at a throwaway SQLite DB and a fixed secret before any test
module imports app.core.config (settings are read once, at import)."""
import os
import tempfile

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mktemp(suffix='.db')}")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

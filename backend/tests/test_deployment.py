"""One-address deployment (Dockerfile / DEPLOY.md): PUBLIC_URL decides the
OAuth redirect, frontend URL and secure cookie, and the API serves the built
web app. Runs in a separate process so the shared test app keeps its routes."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

CHECK = r"""
import json
from fastapi.testclient import TestClient
from app.core.config import settings
from app.main import app

c = TestClient(app)
r = {
    "redirect": settings.google_redirect_uri, "frontend": settings.frontend_url, "secure": settings.cookie_secure,
    "index": c.get("/").text, "deep_link": c.get("/history").text, "asset": c.get("/assets/app.js").text,
    "health": c.get("/health").json(), "api": c.get("/auth/status").status_code,
    "unknown_api": c.get("/api/nope").status_code, "escape": c.get("/..%2F..%2Fsecret.txt").text,
}
print(json.dumps(r))
"""


def test_public_url_and_web_app_served_from_one_address():
    with tempfile.TemporaryDirectory() as tmp:
        static = Path(tmp) / "dist"
        (static / "assets").mkdir(parents=True)
        (static / "index.html").write_text("<html>CloudClean app</html>")
        (static / "assets" / "app.js").write_text("console.log('app')")
        (Path(tmp) / "secret.txt").write_text("do not serve")
        env = {**os.environ, "STATIC_DIR": str(static), "PUBLIC_URL": "https://cloudclean.example.ts.net/",
               "DATABASE_URL": f"sqlite:///{Path(tmp) / 'deploy.db'}"}
        out = subprocess.run([sys.executable, "-c", CHECK], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stderr
        r = json.loads(out.stdout.strip().splitlines()[-1])

    assert r["redirect"] == "https://cloudclean.example.ts.net/auth/callback"
    assert r["frontend"] == "https://cloudclean.example.ts.net" and r["secure"] is True
    assert "CloudClean app" in r["index"] and "CloudClean app" in r["deep_link"]  # the web app routes itself
    assert r["asset"] == "console.log('app')"
    assert r["health"] == {"status": "ok"} and r["api"] == 200
    assert r["unknown_api"] == 404
    assert "do not serve" not in r["escape"]

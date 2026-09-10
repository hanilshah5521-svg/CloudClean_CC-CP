"""End-to-end integration test against Demo Mode (no real Google account
needed): Connect -> Analyze -> Recommend -> Optimize -> Refresh."""
import os
import tempfile

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mktemp(suffix='.db')}")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()  # TestClient() without a `with` block doesn't fire startup events
client = TestClient(app)


def test_full_demo_lifecycle():
    # Connect (Demo Mode — no OAuth needed)
    r = client.post("/auth/demo")
    assert r.status_code == 200

    r = client.get("/api/user")
    assert r.status_code == 200
    assert r.json()["is_demo"] is True

    # Analyze
    r = client.post("/api/analyze")
    assert r.status_code == 200
    body = r.json()
    assert body["files_analyzed"] > 0
    assert 0 <= body["optimization_score"] <= 100

    # Recommend
    r = client.get("/api/recommendations")
    assert r.status_code == 200
    recs = r.json()
    assert len(recs) > 0
    for rec in recs:
        assert rec["reason"]  # every recommendation must explain itself
        assert rec["risk"] in ("low", "medium", "high")

    # Storage overview reflects the analysis
    storage_before = client.get("/api/storage").json()
    assert storage_before["used_bytes"] > 0

    # Optimize: compress the first compression candidate, if any
    candidates = client.get("/api/compression/candidates").json()
    if candidates:
        target = candidates[0]
        r = client.post(f"/api/compression/{target['file_id']}")
        assert r.status_code == 200
        result = r.json()
        if result["success"]:
            assert result["new_size_bytes"] < result["original_size_bytes"]

    # Duplicates: trash the non-kept file in the first group, if any
    groups = client.get("/api/duplicates").json()
    if groups:
        group = groups[0]
        keep = group["recommended_keep_drive_id"]
        r = client.post(f"/api/duplicates/{group['id']}/trash", json={"keep_drive_id": keep})
        assert r.status_code == 200

    # History was written for whatever actions succeeded
    history = client.get("/api/history").json()
    assert len(history) >= 1
    for entry in history:
        assert entry["status"] in ("success", "skipped", "failed")

    # Refresh: re-analyze re-queries state rather than just subtracting
    r = client.post("/api/analyze")
    assert r.status_code == 200
    storage_after = client.get("/api/storage").json()
    assert storage_after["used_bytes"] <= storage_before["used_bytes"]


def test_unauthenticated_requests_are_rejected():
    fresh_client = TestClient(app)
    r = fresh_client.get("/api/storage")
    assert r.status_code == 401

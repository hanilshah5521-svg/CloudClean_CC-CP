"""Everything the UI links to in Google Drive ("Open in Drive", "Show in
folder") needs the file's Drive ID, link and parent folder in each list."""
from fastapi.testclient import TestClient

from app.core.database import init_db
from app.main import app

init_db()

LINK_KEYS = {"drive_id", "web_url", "parent_id"}


def test_lists_carry_what_drive_links_need():
    c = TestClient(app)
    c.post("/auth/demo")
    c.post("/api/analyze")

    files = c.get("/api/files").json()["files"]
    assert files and all(LINK_KEYS <= f.keys() for f in files)
    assert all(f["parent_id"] for f in files)  # demo files all sit in a folder

    groups = c.get("/api/duplicates").json()
    assert groups and all(LINK_KEYS <= f.keys() for g in groups for f in g["files"])

    candidates = c.get("/api/compression/candidates").json()
    videos = c.get("/api/compression/video-candidates").json()
    assert candidates and all(LINK_KEYS <= x.keys() for x in candidates)
    assert all(LINK_KEYS <= x.keys() for x in videos["candidates"] + videos["not_suggested"])

    recs = [r for r in c.get("/api/recommendations").json() if r["file_id"]]
    assert recs and all(r["file_drive_id"] and r["file_web_url"] is not None for r in recs)

    for s in c.get("/api/organize").json():
        assert "parent_id" in s


def test_history_rows_name_the_drive_item_they_touched():
    c = TestClient(app)
    c.post("/auth/demo")
    c.post("/api/analyze")
    target = c.get("/api/compression/candidates").json()[0]
    c.put("/api/settings", json={"min_saving_percent": 1})
    c.post(f"/api/compression/{target['file_id']}")

    row = next(h for h in c.get("/api/history").json() if h["action"] == "compressed")
    assert row["file_drive_id"] == target["drive_id"]

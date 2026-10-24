"""A compression whose real saving is too small says what was measured, and the
file isn't suggested again — until it's modified in Drive."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.core.database import SessionLocal, init_db
from app.main import app
from app.models import DriveFile

init_db()


def test_skipped_compression_reports_measurement_and_is_not_suggested_again():
    c = TestClient(app)
    c.post("/auth/demo")
    c.post("/api/analyze")
    target = c.get("/api/compression/candidates").json()[0]

    c.put("/api/settings", json={"min_saving_percent": 90})  # nothing realistic reaches 90%
    res = c.post(f"/api/compression/{target['file_id']}").json()
    assert res["success"] is False
    assert "% (" in res["message"] and "below your 90% minimum" in res["message"]
    assert "nothing was uploaded" in res["message"]

    c.put("/api/settings", json={"min_saving_percent": 10})
    assert target["file_id"] not in {x["file_id"] for x in c.get("/api/compression/candidates").json()}
    c.post("/api/analyze")
    names = {x["name"] for x in c.get("/api/compression/candidates").json()}
    assert target["name"] not in names  # tried once, not suggested again

    # The file is edited in Drive after the attempt -> worth measuring again.
    with SessionLocal() as db:
        row = db.query(DriveFile).filter(DriveFile.name == target["name"], DriveFile.is_trashed.is_(False)).order_by(
            DriveFile.id.desc()).first()
        row.modified_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).replace(tzinfo=None)
        db.commit()
    c.post("/api/analyze")
    assert target["name"] in {x["name"] for x in c.get("/api/compression/candidates").json()}

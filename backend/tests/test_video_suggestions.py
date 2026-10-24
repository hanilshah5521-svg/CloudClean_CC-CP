"""Videos are either suggested for compression or listed with the reason they
aren't — never silently missing — and never suggested when the worker would
refuse them."""
from fastapi.testclient import TestClient

from app.analyzers.compression_potential import estimate
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.main import app
from app.models import DriveFile

init_db()
MB = 1024 * 1024


def test_video_over_the_worker_limit_is_not_suggested(monkeypatch):
    monkeypatch.setattr(settings, "video_max_mb", 4096)
    too_big = estimate("video", ".mp4", 6 * 1024 * MB, duration_ms=3_200_000, width=1920, height=1080)
    assert not too_big.compressible and "VIDEO_MAX_MB" in too_big.reason
    fits = estimate("video", ".mp4", 900 * MB, duration_ms=1_160_000, width=1904, height=802)
    assert fits.compressible


def test_video_drive_has_not_processed_yet_says_so():
    est = estimate("video", ".mp4", 500 * MB)  # no duration from Drive yet
    assert not est.compressible and "Re-analyze later" in est.reason


def test_every_video_is_a_candidate_or_has_a_reason():
    client = TestClient(app)
    client.post("/auth/demo")
    client.post("/api/analyze")
    user_id = client.get("/api/user").json()["id"]
    with SessionLocal() as db:  # a short screen recording, like a real Drive would have
        db.add(DriveFile(user_id=user_id, drive_id="small-clip", name="Screen Recording.mp4", mime_type="video/mp4",
                         extension=".mp4", category="video", size_bytes=30 * MB, video_duration_ms=36_000,
                         video_width=1912, video_height=896))
        db.commit()
        all_videos = sorted(f.id for f in db.query(DriveFile).filter(
            DriveFile.user_id == user_id, DriveFile.category == "video", DriveFile.is_trashed.is_(False)))

    data = client.get("/api/compression/video-candidates").json()
    listed = sorted([v["file_id"] for v in data["candidates"]] + [v["file_id"] for v in data["not_suggested"]])
    assert listed == all_videos
    small = next(v for v in data["not_suggested"] if v["name"] == "Screen Recording.mp4")
    assert "Under 50 MB" in small["reason"]

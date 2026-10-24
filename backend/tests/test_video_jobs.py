"""The compress_video job against a fake Drive that keeps file content on disk
(and every replaced version as a revision, like Drive). With ffmpeg
installed, a real 2-second clip is generated and re-encoded; the bookkeeping
tests use a stand-in encoder so they run everywhere."""
import hashlib
import shutil
import subprocess
import uuid

import pytest
from fastapi.testclient import TestClient

from app.analyzers.compression_potential import estimate
from app.compression import video
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.main import app
from app.models import DriveFile, Job, OptimizationAction, User, UserSettings
from app.services import job_service, optimization_service, video_service

init_db()
MB = 1024 * 1024


class DiskDrive:
    """Drive stand-in for big files: content lives on disk and only the
    streaming methods exist, so any attempt to load a video into memory
    (download_file / download_revision / replace_content) fails the test."""

    def __init__(self, root, file_id, content: bytes, mime="video/mp4"):
        self.root, self.file_id, self.mime = root, file_id, mime
        self.head = root / f"{file_id}.head"
        self.head.write_bytes(content)
        self.revisions = []  # revision i = content before the i-th update
        self.deleted_revisions = set()
        self.fail_upload = False

    def get_file(self, file_id):
        return {"id": file_id, "size": str(self.head.stat().st_size), "mimeType": self.mime,
                "headRevisionId": f"rev{len(self.revisions)}", "modifiedTime": "2020-01-01T00:00:00Z",
                "md5Checksum": hashlib.md5(self.head.read_bytes()).hexdigest()}

    def get_revision(self, file_id, revision_id):
        path = self.revisions[int(revision_id.removeprefix("rev"))]
        return {"id": revision_id, "keepForever": True, "md5Checksum": hashlib.md5(path.read_bytes()).hexdigest()}

    def delete_revision(self, file_id, revision_id):
        self.deleted_revisions.add(revision_id)
        return True

    def download_to_file(self, file_id, path, on_progress=None):
        shutil.copyfile(self.head, path)
        if on_progress:
            on_progress(1.0)

    def download_revision_to_file(self, file_id, revision_id, path, on_progress=None):
        shutil.copyfile(self.revisions[int(revision_id.removeprefix("rev"))], path)

    def replace_content_from_file(self, file_id, path, mime_type, on_progress=None):
        if self.fail_upload:
            raise ConnectionError("network went away")
        kept = self.root / f"{file_id}.rev{len(self.revisions)}"
        shutil.copyfile(self.head, kept)
        self.revisions.append(kept)
        shutil.copyfile(path, self.head)
        return self.get_file(file_id)


@pytest.fixture
def workdir(monkeypatch, tmp_path):
    path = tmp_path / "work"
    monkeypatch.setattr(settings, "job_temp_dir", str(path))
    return path


def _setup(monkeypatch, tmp_path, content: bytes, min_saving=10.0, ext=".mp4"):
    drive_id = f"vid-{uuid.uuid4().hex[:8]}"
    drive = DiskDrive(tmp_path, drive_id, content)
    monkeypatch.setattr(video_service, "get_client", lambda user: drive)
    monkeypatch.setattr(optimization_service, "get_client", lambda user: drive)
    with SessionLocal() as db:
        user = User(email=f"vid-{uuid.uuid4().hex}@example.com", name="V", is_demo=False, refresh_token="r")
        db.add(user)
        db.flush()
        db.add(UserSettings(user_id=user.id, min_saving_percent=min_saving))
        db.add(DriveFile(user_id=user.id, drive_id=drive_id, name=f"clip{ext}", mime_type="video/mp4", extension=ext,
                         category="video", size_bytes=len(content), recommendation_type="compress"))
        db.commit()
        return drive, user.id, drive_id


def _run(user_id, kind, payload, target=""):
    with SessionLocal() as db:
        job_id = job_service.create_job(db, db.get(User, user_id), kind, payload, target=target).id
    job_service.run_job(job_id)
    with SessionLocal() as db:
        return db.get(Job, job_id)


def _compressed_action(db, user_id):
    return db.query(OptimizationAction).filter_by(user_id=user_id, action="compressed").order_by(
        OptimizationAction.id.desc()).first()


def _assert_undo_restores_original(drive, user_id, original: bytes, workdir):
    with SessionLocal() as db:
        action = _compressed_action(db, user_id)
        assert action.restorable and action.revision_id == "rev0"
        # A video's undo streams GBs, so the History route hands it to the worker.
        assert optimization_service.restore_runs_in_background(db, db.get(User, user_id), action)
        action_id = action.id
    job = _run(user_id, "restore", {"action_id": action_id}, target=str(action_id))
    assert job.status == "done", job.error
    assert drive.head.read_bytes() == original  # Drive's head is the original bytes again
    with SessionLocal() as db:
        assert db.get(OptimizationAction, action_id).status == "reverted"
        row = db.query(DriveFile).filter_by(user_id=user_id).one()
        assert row.size_bytes == len(original)
    assert list(workdir.glob("cloudclean-job-*")) == []


# ---- with real ffmpeg -------------------------------------------------------

requires_ffmpeg = pytest.mark.skipif(not video.ffmpeg_available(), reason="ffmpeg/ffprobe not installed")


def _make_clip(path):
    """2 s, 320x240, lossless H.264 + a sine tone: big for its length, so
    CRF 27 shrinks it a lot."""
    subprocess.run([
        video.find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", str(path),
    ], check=True, timeout=120)
    return path.read_bytes()


@requires_ffmpeg
def test_video_job_reencodes_uploads_new_revision_and_undo_restores_it(monkeypatch, tmp_path, workdir):
    original = _make_clip(tmp_path / "source.mp4")
    drive, user_id, drive_id = _setup(monkeypatch, tmp_path, original)

    job = _run(user_id, "compress_video", {"drive_id": drive_id}, target=drive_id)
    assert job.status == "done", job.error
    assert job.result["success"] and job.progress == 100
    assert job.result["new_size_bytes"] < len(original)

    # Same file ID, new revision; the original kept as rev0.
    assert len(drive.revisions) == 1 and drive.revisions[0].read_bytes() == original
    encoded = video.probe(drive.head)
    assert encoded.video_codec == "h264" and encoded.has_audio
    assert (encoded.width, encoded.height) == (320, 240)  # same resolution
    assert abs(encoded.duration_s - 2.0) <= 1.0
    assert list(workdir.glob("cloudclean-job-*")) == []  # temp files deleted

    with SessionLocal() as db:
        row = db.query(DriveFile).filter_by(user_id=user_id).one()
        assert row.size_bytes == job.result["new_size_bytes"] and row.recommendation_type == "already_optimized"
    _assert_undo_restores_original(drive, user_id, original, workdir)


@requires_ffmpeg
def test_video_job_keeps_the_original_when_the_saving_is_too_small(monkeypatch, tmp_path, workdir):
    original = _make_clip(tmp_path / "source.mp4")
    drive, user_id, drive_id = _setup(monkeypatch, tmp_path, original, min_saving=90)
    job = _run(user_id, "compress_video", {"drive_id": drive_id}, target=drive_id)
    assert job.status == "done" and job.result["success"] is False
    assert "minimum is 90%" in job.result["message"]
    assert drive.revisions == [] and drive.head.read_bytes() == original  # nothing uploaded
    with SessionLocal() as db:
        assert _compressed_action(db, user_id).status == "skipped"
    assert list(workdir.glob("cloudclean-job-*")) == []


# ---- bookkeeping, with a stand-in encoder (no ffmpeg needed) ---------------

@pytest.fixture
def fake_ffmpeg(monkeypatch):
    info = video.VideoInfo(duration_s=2.0, video_index=0, video_codec="h264", pix_fmt="yuv420p", color_transfer="",
                           width=320, height=240, audio_streams=1, subtitle_streams=0)
    monkeypatch.setattr(video_service, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(video_service, "probe", lambda path: info)

    def transcode(src, dst, source, ext, on_progress=None):
        dst.write_bytes(src.read_bytes()[: len(src.read_bytes()) // 3])  # "a third of the size"
        on_progress(1.0)

    monkeypatch.setattr(video_service, "transcode", transcode)
    return info


def test_video_job_records_original_revision_and_undo_restores_it(monkeypatch, tmp_path, workdir, fake_ffmpeg):
    original = b"\x00fake-video-bytes" * 4096
    drive, user_id, drive_id = _setup(monkeypatch, tmp_path, original)
    job = _run(user_id, "compress_video", {"drive_id": drive_id}, target=drive_id)
    assert job.status == "done" and job.result["success"], job.error
    assert drive.head.stat().st_size == len(original) // 3
    _assert_undo_restores_original(drive, user_id, original, workdir)


def test_failed_upload_leaves_a_history_entry_naming_the_original(monkeypatch, tmp_path, workdir, fake_ffmpeg):
    original = b"\x01" * 300_000
    drive, user_id, drive_id = _setup(monkeypatch, tmp_path, original)
    drive.fail_upload = True
    job = _run(user_id, "compress_video", {"drive_id": drive_id}, target=drive_id)
    assert job.status == "failed" and "Uploading" in job.error
    with SessionLocal() as db:
        action = _compressed_action(db, user_id)
        assert action.status == "failed" and "rev0" in action.detail
    assert drive.head.read_bytes() == original
    assert list(workdir.glob("cloudclean-job-*")) == []  # cleaned up on failure too


def test_unsafe_videos_are_skipped_before_encoding(monkeypatch, tmp_path, workdir, fake_ffmpeg):
    monkeypatch.setattr(video_service, "probe", lambda path: video.VideoInfo(
        duration_s=2.0, video_index=0, video_codec="hevc", pix_fmt="yuv420p10le", color_transfer="arib-std-b67",
        width=1920, height=1080, audio_streams=1, subtitle_streams=0))
    monkeypatch.setattr(video_service, "transcode", lambda *a, **k: pytest.fail("must not encode HDR video"))
    drive, user_id, drive_id = _setup(monkeypatch, tmp_path, b"\x02" * 100_000)
    job = _run(user_id, "compress_video", {"drive_id": drive_id}, target=drive_id)
    assert job.status == "done" and not job.result["success"] and "HDR" in job.result["message"]
    assert drive.revisions == []


def test_in_request_compression_refuses_videos():
    with SessionLocal() as db:
        user = User(email=f"v-{uuid.uuid4().hex}@example.com", is_demo=False, refresh_token="r")
        db.add(user)
        db.flush()
        db.add(UserSettings(user_id=user.id))
        row = DriveFile(user_id=user.id, drive_id="x", name="x.mp4", mime_type="video/mp4", extension=".mp4",
                        category="video", size_bytes=900 * MB)
        db.add(row)
        db.commit()
        with pytest.raises(optimization_service.OptimizationError, match="background worker"):
            optimization_service.compress_file(db, user, row)


# ---- estimate + Demo Mode API ----------------------------------------------

def test_video_estimate_is_bitrate_based():
    ten_min = 10 * 60 * 1000
    phone = estimate("video", ".mp4", 1275 * MB, duration_ms=ten_min, width=1920, height=1080)  # ~17 Mbps
    assert phone.compressible and phone.estimated_ratio > 0.6 and phone.method == "video_reencode"
    screen = estimate("video", ".mp4", 165 * MB, duration_ms=ten_min, width=1280, height=720)  # ~2.2 Mbps
    assert not screen.compressible
    assert not estimate("video", ".mp4", 1275 * MB).compressible  # no duration: no guess
    assert not estimate("video", ".webm", 1275 * MB, duration_ms=ten_min, width=1920, height=1080).compressible
    portrait = estimate("video", ".mov", 1275 * MB, duration_ms=ten_min, width=1080, height=1920)
    assert portrait.details["target_kbps"] == phone.details["target_kbps"]  # orientation doesn't matter


def test_demo_video_compression_runs_as_a_job_and_can_be_undone():
    client = TestClient(app)
    client.post("/auth/demo")
    client.post("/api/analyze")
    data = client.get("/api/compression/video-candidates").json()
    assert data["candidates"] and data["ffmpeg_available"]
    assert all(c["current_kbps"] > c["target_kbps"] for c in data["candidates"])
    # Videos are not offered for in-request compression.
    assert not {c["file_id"] for c in client.get("/api/compression/candidates").json()} & {
        c["file_id"] for c in data["candidates"]}

    target = data["candidates"][0]
    job = client.post(f"/api/compression/{target['file_id']}/video").json()
    assert job["kind"] == "compress_video" and job["status"] == "done" and job["result"]["success"]
    entry = next(h for h in client.get("/api/history").json() if h["action"] == "compressed")
    assert entry["restorable"]
    assert client.post(f"/api/history/{entry['id']}/restore").json()["success"]  # demo: inline
    assert client.get(f"/api/files/{target['file_id']}").json()["size_bytes"] == target["current_size_bytes"]

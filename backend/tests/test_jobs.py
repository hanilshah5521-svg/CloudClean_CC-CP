"""Background jobs: atomic claiming, progress, failure bookkeeping, crash
recovery, the worker loop, and POST /api/analyze as a job (Demo Mode inline,
real accounts queued for the worker)."""
import uuid

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, get_db, init_db
from app.main import app
from app.models import Job, OptimizationAction, User, UserSettings
from app.security.session import get_current_user
from app.services import drive_service, job_handlers, job_service
from app.services.optimization_service import OptimizationError
from app.worker import Worker

init_db()


def _real_user(db):
    user = User(email=f"jobs-{uuid.uuid4().hex}@example.com", name="Real", is_demo=False, refresh_token="r")
    db.add(user)
    db.flush()
    db.add(UserSettings(user_id=user.id))
    db.commit()
    return user


@pytest.fixture
def fake_kind(monkeypatch):
    """Registers a throwaway job kind whose behaviour each test supplies."""
    holder = {}
    monkeypatch.setitem(job_handlers.HANDLERS, "test_kind", lambda db, user, payload, progress: holder["fn"](db, user, payload, progress))
    return holder


def test_claim_is_atomic_and_takes_the_oldest_job_first():
    with SessionLocal() as db:
        user = _real_user(db)
        first = job_service.create_job(db, user, "test_kind")
        second = job_service.create_job(db, user, "test_kind")
        others = [j.id for j in db.query(Job).filter(Job.status == "queued", Job.id < first.id)]
        for job_id in others:  # leftovers from other test modules don't concern this test
            job_service.claim_job(db, job_id)

        assert job_service.claim_next_job(db) == first.id
        assert job_service.claim_job(db, first.id) is False  # already running: a second claim loses
        assert job_service.claim_next_job(db) == second.id
        assert job_service.claim_next_job(db) is None
        db.refresh(first)
        assert first.status == "running" and first.started_at is not None


def test_progress_is_written_while_the_job_runs_and_result_on_completion(fake_kind):
    seen = []

    def handler(db, user, payload, progress):
        progress(40, "Halfway there")
        with SessionLocal() as other:  # what the API's polling would see
            row = other.get(Job, job_id)
            seen.append((row.status, row.progress, row.message))
        return {"answer": payload["n"] * 2}

    fake_kind["fn"] = handler
    with SessionLocal() as db:
        job_id = job_service.create_job(db, _real_user(db), "test_kind", {"n": 21}).id
    job_service.run_job(job_id)

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert seen == [("running", 40, "Halfway there")]
        assert (job.status, job.progress, job.result, job.error) == ("done", 100, {"answer": 42}, "")
        assert job.finished_at is not None


def test_failing_job_records_the_error_and_keeps_partial_work_out(fake_kind):
    def handler(db, user, payload, progress):
        db.add(OptimizationAction(user_id=user.id, file_name="half-done", action="compressed"))
        raise OptimizationError("Nope, not this file.")

    fake_kind["fn"] = handler
    with SessionLocal() as db:
        user = _real_user(db)
        user_id, job_id = user.id, job_service.create_job(db, user, "test_kind").id
    job_service.run_job(job_id)  # never raises
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert (job.status, job.error) == ("failed", "Nope, not this file.")
        assert db.query(OptimizationAction).filter_by(user_id=user_id).count() == 0  # rolled back


def test_unexpected_errors_are_not_leaked_to_the_user(fake_kind):
    fake_kind["fn"] = lambda *a: 1 / 0
    with SessionLocal() as db:
        job_id = job_service.create_job(db, _real_user(db), "test_kind").id
    job_service.run_job(job_id)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "failed" and "ZeroDivision" not in job.error and "worker's log" in job.error


def test_worker_restart_fails_interrupted_jobs_and_flags_half_uploads():
    with SessionLocal() as db:
        user = _real_user(db)
        job = job_service.create_job(db, user, "compress_video")
        job_service.claim_job(db, job.id)
        action = OptimizationAction(user_id=user.id, file_name="v.mp4", action="compressed", status="in_progress",
                                    revision_id="rev7")
        db.add(action)
        db.commit()
        assert job_service.recover_interrupted(db) >= 1
        db.refresh(job)
        db.refresh(action)
        assert job.status == "failed" and "Interrupted" in job.error
        assert action.status == "failed" and "rev7" in action.detail and not action.restorable


def test_worker_runs_queued_jobs_and_reports_heartbeat(fake_kind, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "job_temp_dir", str(tmp_path))  # startup cleans leftover temp dirs there
    fake_kind["fn"] = lambda db, user, payload, progress: {"ok": True}
    with SessionLocal() as db:
        user = _real_user(db)
        ids = [job_service.create_job(db, user, "test_kind").id for _ in range(2)]
        # Only this test's jobs should be in the queue.
        db.query(Job).filter(Job.status == "queued", Job.id.notin_(ids)).update({Job.status: "failed"})
        db.commit()

    worker = Worker(poll_seconds=0)
    worker.startup()
    with SessionLocal() as db:
        assert job_service.worker_online(db)
    assert worker.run_pending() == 2
    worker.remove_heartbeat()
    with SessionLocal() as db:
        assert [db.get(Job, i).status for i in ids] == ["done", "done"]
        assert not job_service.worker_online(db)


# ---- POST /api/analyze as a job --------------------------------------------

def test_demo_analyze_runs_inline_as_a_job():
    client = TestClient(app)
    client.post("/auth/demo")
    r = client.post("/api/analyze")
    assert r.status_code == 200
    body = r.json()
    assert (body["kind"], body["status"], body["progress"]) == ("analyze", "done", 100)
    assert body["files_analyzed"] == body["result"]["files_analyzed"] > 0  # summary still in the response

    job = client.get(f"/api/jobs/{body['job_id']}").json()
    assert job["status"] == "done" and job["worker_online"]
    assert client.get("/api/analysis").json()["analyzed"]
    assert client.get("/api/jobs", params={"kind": "analyze"}).json()[0]["id"] == body["job_id"]

    stranger = TestClient(app)
    stranger.post("/auth/demo")
    assert stranger.get(f"/api/jobs/{body['job_id']}").status_code == 404  # owner only


class ListingDrive:
    def storage_quota(self):
        return {"used_bytes": 300, "quota_bytes": 1000, "drive_bytes": 300, "drive_trash_bytes": 0,
                "gmail_photos_bytes": 0}

    def iter_all_files(self):
        yield {"id": "f1", "name": "a.pdf", "mimeType": "application/pdf", "size": "100", "md5Checksum": "x"}
        yield {"id": "f2", "name": "a (1).pdf", "mimeType": "application/pdf", "size": "100", "md5Checksum": "x"}
        yield {"id": "f3", "name": "clip.mp4", "mimeType": "video/mp4", "size": "100",
               "videoMediaMetadata": {"width": 640, "height": 360, "durationMillis": "2000"}}


@pytest.fixture
def real_client(monkeypatch):
    """An API client signed in as a real (non-demo) account, with a fake Drive."""
    with SessionLocal() as db:
        user_id = _real_user(db).id

    def current_user(db: Session = Depends(get_db)):
        return db.get(User, user_id)

    app.dependency_overrides[get_current_user] = current_user
    monkeypatch.setattr(drive_service, "get_client", lambda user: ListingDrive())
    yield TestClient(app), user_id
    app.dependency_overrides.pop(get_current_user, None)


def test_real_analyze_is_queued_for_the_worker_and_polled(real_client):
    client, user_id = real_client
    r = client.post("/api/analyze")
    assert r.status_code == 202
    job = r.json()
    assert job["status"] == "queued" and "files_analyzed" not in job
    assert client.post("/api/analyze").json()["job_id"] == job["job_id"]  # no duplicate job while queued

    with SessionLocal() as db:  # leave only this job in the queue
        db.query(Job).filter(Job.status == "queued", Job.id != job["job_id"]).update({Job.status: "failed"})
        db.commit()
    Worker(poll_seconds=0).run_pending()

    done = client.get(f"/api/jobs/{job['job_id']}").json()
    assert done["status"] == "done" and done["progress"] == 100
    assert done["result"]["files_analyzed"] == 3 and done["result"]["duplicates_found"] == 2
    with SessionLocal() as db:
        video = db.query(drive_service.DriveFile).filter_by(user_id=user_id, drive_id="f3").one()
        assert (video.video_width, video.video_height, video.video_duration_ms) == (640, 360, 2000)

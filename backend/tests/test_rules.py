"""Auto-compression rules: suggestions, auto-apply (off by default), the
nightly schedule, and the live re-check before a rule touches a file."""
import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.main import app
from app.models import CompressionRule, DriveFile, Job, User, UserSettings
from app.services import rules_service

init_db()


def _demo():
    client = TestClient(app)
    client.post("/auth/demo")
    client.post("/api/analyze")
    return client


def _rule(**overrides):
    return {"category": "video", "min_size_mb": 100, "min_inactive_days": 30, "enabled": True, **overrides}


def test_rules_create_suggestions_without_touching_files():
    client = _demo()
    created = client.post("/api/rules", json=_rule()).json()
    assert created["auto_apply"] is False  # off unless explicitly enabled

    run = client.post("/api/rules/run").json()
    assert run["status"] == "done" and run["result"]["new_suggestions"] > 0 and run["result"]["auto_applied"] == 0
    suggestions = client.get("/api/rules/suggestions").json()
    assert suggestions and all(s["status"] == "pending" for s in suggestions)
    assert not [h for h in client.get("/api/history").json() if h["action"] == "compressed"]
    # Already-efficient videos are never suggested, however big.
    assert "tutorial_recording.mp4" not in {s["file_name"] for s in suggestions}
    assert client.get("/api/rules").json()["last_run_at"]

    # Re-running doesn't duplicate; a dismissed file stays dismissed.
    assert client.post("/api/rules/run").json()["result"]["new_suggestions"] == 0
    dismissed = client.post(f"/api/rules/suggestions/{suggestions[0]['id']}/dismiss").json()
    assert dismissed["status"] == "dismissed"
    client.post("/api/rules/run")
    assert suggestions[0]["id"] not in {s["id"] for s in client.get("/api/rules/suggestions").json()}

    # Applying one runs the compression job (inline in Demo Mode).
    job = client.post(f"/api/rules/suggestions/{suggestions[1]['id']}/apply").json()
    assert job["kind"] == "compress_video" and job["result"]["success"]
    applied = {s["id"]: s for s in client.get("/api/rules/suggestions", params={"status": "all"}).json()}
    assert applied[suggestions[1]["id"]]["status"] == "applied"


def test_auto_apply_compresses_up_to_the_nightly_cap_and_never_redoes_an_undo(monkeypatch):
    monkeypatch.setattr(settings, "rules_max_auto_apply", 2)
    client = _demo()
    client.post("/api/rules", json=_rule(auto_apply=True))
    result = client.post("/api/rules/run").json()["result"]
    assert result["auto_applied"] == 2
    statuses = [s["status"] for s in client.get("/api/rules/suggestions", params={"status": "all"}).json()]
    assert statuses.count("applied") == 2 and "pending" in statuses

    # The user undoes one: the next run must not compress it again.
    undo = next(h for h in client.get("/api/history").json() if h["action"] == "compressed")
    client.post(f"/api/history/{undo['id']}/restore")
    client.post("/api/analyze")
    client.post("/api/rules/run")
    compressed = [h for h in client.get("/api/history").json() if h["action"] == "compressed"]
    assert sum(h["file_name"] == undo["file_name"] for h in compressed) == 1


def test_rule_validation_and_ownership():
    client = _demo()
    assert client.post("/api/rules", json=_rule(category="spreadsheets")).status_code == 422
    assert client.post("/api/rules", json=_rule(min_size_mb=0)).status_code == 422
    rule = client.post("/api/rules", json=_rule()).json()
    stranger = _demo()
    assert stranger.put(f"/api/rules/{rule['id']}", json=_rule()).status_code == 404
    assert stranger.delete(f"/api/rules/{rule['id']}").status_code == 404
    assert client.delete(f"/api/rules/{rule['id']}").json() == {"ok": True}


def test_file_edited_since_the_rule_matched_is_left_alone():
    client = _demo()
    client.post("/api/rules", json=_rule())
    client.post("/api/rules/run")
    suggestion = client.get("/api/rules/suggestions").json()[0]
    user_id = client.get("/api/user").json()["id"]
    with SessionLocal() as db:  # the file was edited after the rule matched it
        row = db.query(DriveFile).filter_by(user_id=user_id, drive_id=suggestion["drive_id"]).one()
        row.modified_time = datetime.utcnow()
        db.commit()
    job = client.post(f"/api/rules/suggestions/{suggestion['id']}/apply").json()
    assert job["status"] == "done" and not job["result"]["success"] and "changed" in job["result"]["message"]
    status = {s["id"]: s["status"] for s in client.get("/api/rules/suggestions", params={"status": "all"}).json()}
    assert status[suggestion["id"]] == "skipped"


def test_nightly_schedule_queues_each_user_once_per_day():
    hour = settings.rules_hour_utc
    with SessionLocal() as db:
        user = User(email=f"sched-{uuid.uuid4().hex}@example.com", is_demo=False, refresh_token="r")
        db.add(user)
        db.flush()
        db.add(UserSettings(user_id=user.id))
        scheduled = datetime(2026, 3, 10, hour)
        db.add(CompressionRule(user_id=user.id, created_at=scheduled - timedelta(days=2)))
        db.commit()

        def evaluation_jobs():
            return db.query(Job).filter_by(user_id=user.id, kind="evaluate_rules").count()

        rules_service.schedule_due_evaluations(db, now=scheduled - timedelta(minutes=5))
        assert evaluation_jobs() == 1  # never evaluated, and yesterday's slot has passed
        rules_service.schedule_due_evaluations(db, now=scheduled - timedelta(minutes=4))
        assert evaluation_jobs() == 1  # one already queued

        db.query(Job).filter_by(user_id=user.id).update({Job.status: "done"})
        user.settings.rules_last_run_at = scheduled - timedelta(minutes=3)
        db.commit()
        rules_service.schedule_due_evaluations(db, now=scheduled - timedelta(minutes=1))
        assert evaluation_jobs() == 1  # ran after yesterday's slot: not due until tonight
        rules_service.schedule_due_evaluations(db, now=scheduled + timedelta(minutes=1))
        assert evaluation_jobs() == 2  # tonight's run

        # A rule created after the last slot waits for the next one.
        db.query(Job).filter_by(user_id=user.id).update({Job.status: "done"})
        db.query(CompressionRule).filter_by(user_id=user.id).update({CompressionRule.created_at: scheduled + timedelta(hours=1)})
        user.settings.rules_last_run_at = None
        db.commit()
        rules_service.schedule_due_evaluations(db, now=scheduled + timedelta(hours=2))
        assert evaluation_jobs() == 2

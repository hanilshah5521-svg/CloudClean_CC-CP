"""Restore, in-place compression, partial failures and Gmail — through the
real HTTP API (Demo Mode) and through the service layer with a fake Drive
client standing in for Google."""
import hashlib
import uuid

import pytest
from fastapi.testclient import TestClient
from googleapiclient.errors import HttpError

from app.core.database import SessionLocal, init_db
from app.main import app
from app.models import DriveFile, DuplicateGroup, OptimizationAction, User, UserSettings
from app.services import optimization_service as svc

init_db()


@pytest.fixture
def demo():
    client = TestClient(app)
    assert client.post("/auth/demo").status_code == 200
    assert client.post("/api/analyze").status_code == 200
    return client


def _history(client, action):
    return [h for h in client.get("/api/history").json() if h["action"] == action]


def test_version_groups_need_explicit_acknowledgement(demo):
    groups = demo.get("/api/duplicates").json()
    versions = next(g for g in groups if g["review_only"])
    assert versions["potential_recovery_bytes"] == 0
    keep = versions["recommended_keep_drive_id"]
    r = demo.post(f"/api/duplicates/{versions['id']}/trash", json={"keep_drive_id": keep})
    assert r.status_code == 400 and "different content" in r.json()["detail"]
    r = demo.post(f"/api/duplicates/{versions['id']}/trash",
                  json={"keep_drive_id": keep, "acknowledge_different_content": True})
    assert r.status_code == 200 and all(t["success"] for t in r.json()["trashed"])


def test_trashed_duplicates_move_to_pending_trash_and_can_be_restored(demo):
    before = demo.get("/api/storage").json()
    group = next(g for g in demo.get("/api/duplicates").json() if not g["review_only"])
    demo.post(f"/api/duplicates/{group['id']}/trash", json={"keep_drive_id": group["recommended_keep_drive_id"]})
    demo.post("/api/analyze")
    after = demo.get("/api/storage").json()
    # Trashed files still use quota until Drive's Trash is emptied.
    assert after["drive_trash_bytes"] == group["potential_recovery_bytes"]
    assert after["used_bytes"] == before["used_bytes"]

    entry = _history(demo, "trashed")[0]
    assert entry["restorable"]
    assert demo.post(f"/api/history/{entry['id']}/restore").status_code == 200
    assert not _history(demo, "trashed")[0]["restorable"]  # now reverted


def test_compression_can_be_undone_from_history(demo):
    candidate = demo.get("/api/compression/candidates").json()[0]
    result = demo.post(f"/api/compression/{candidate['file_id']}").json()
    assert result["success"]
    entry = _history(demo, "compressed")[0]
    assert entry["restorable"]
    assert demo.post(f"/api/history/{entry['id']}/restore").status_code == 200
    restored = demo.get(f"/api/files/{candidate['file_id']}").json()
    assert restored["size_bytes"] == candidate["current_size_bytes"]


def test_archive_counts_savings_once_and_originals_are_restorable(demo):
    files = demo.get("/api/files", params={"filter": "archive_candidate", "page_size": 3}).json()["files"]
    assert files, "demo data should contain archive candidates"
    res = demo.post("/api/archive", json={"file_ids": [x["id"] for x in files], "archive_name": "old"}).json()
    assert res["success"] and res["archive_name"] == "old.zip"

    history = demo.get("/api/history").json()
    per_file = [h for h in history if h["action"] == "archived"]
    created = [h for h in history if h["action"] == "archive_created"]
    assert len(per_file) == len(files) and len(created) == 1
    assert sum(h["saved_bytes"] for h in per_file + created) == res["saved_bytes"]
    assert not created[0]["restorable"] and all(h["restorable"] for h in per_file)
    assert demo.post(f"/api/history/{per_file[0]['id']}/restore").status_code == 200


def test_archive_rejects_google_docs(demo):
    doc = demo.get("/api/files", params={"search": "Untitled document"}).json()["files"][0]
    r = demo.post("/api/archive", json={"file_ids": [doc["id"]]})
    assert r.status_code == 400


def test_gmail_large_emails_can_be_trashed_and_restored(demo):
    data = demo.get("/api/gmail").json()
    assert data["access"] == "demo" and data["total"] > 0
    assert all(m["size_bytes"] >= data["min_mb"] * 1024 * 1024 for m in data["messages"])
    target = data["messages"][0]
    r = demo.post("/api/gmail/trash", json={"message_ids": [target["id"]]})
    assert r.status_code == 200 and r.json()["trashed"][0]["saved_bytes"] == target["size_bytes"]
    assert demo.get("/api/gmail").json()["total"] == data["total"] - 1

    demo.post("/api/analyze")  # trashed email stays trashed across re-analysis
    assert demo.get("/api/gmail").json()["total"] == data["total"] - 1

    entry = _history(demo, "gmail_trashed")[0]
    assert demo.post(f"/api/history/{entry['id']}/restore").status_code == 200
    demo.post("/api/analyze")
    assert demo.get("/api/gmail").json()["total"] == data["total"]


# ---- real-Drive code paths, with a fake client in place of Google ---------

class FakeDrive:
    def __init__(self, fail_trash_on=(), keep_forever=True):
        self.fail_trash_on = set(fail_trash_on)
        self.keep_forever = keep_forever
        self.trashed, self.contents, self.revisions = [], {}, {}
        self.deleted_revisions = set()

    def trash_file(self, file_id):
        if file_id in self.fail_trash_on:
            raise HttpError(type("Resp", (), {"status": 403, "reason": "Forbidden"})(), b"no")
        self.trashed.append(file_id)

    def get_file(self, file_id):
        data = self.contents.get(file_id, b"")
        return {"id": file_id, "size": str(len(data)), "headRevisionId": f"rev{len(self.revisions.get(file_id, []))}",
                "mimeType": "application/pdf", "md5Checksum": hashlib.md5(data).hexdigest()}

    def get_revision(self, file_id, revision_id):
        # Like real Drive uploads: the original version is marked keepForever.
        data = self.revisions[file_id][int(revision_id.removeprefix("rev"))]
        return {"id": revision_id, "keepForever": self.keep_forever, "md5Checksum": hashlib.md5(data).hexdigest()}

    def delete_revision(self, file_id, revision_id):
        self.deleted_revisions.add(revision_id)
        return True

    def download_file(self, file_id, mime_type):
        return self.contents[file_id]

    def replace_content(self, file_id, content, mime_type):
        self.revisions.setdefault(file_id, []).append(self.contents[file_id])
        self.contents[file_id] = content

    def download_revision(self, file_id, revision_id):
        return self.revisions[file_id][int(revision_id.removeprefix("rev"))]


def _real_user(db):
    user = User(email=f"real-{uuid.uuid4().hex}@example.com", name="Real", is_demo=False, refresh_token="r")
    db.add(user)
    db.flush()
    db.add(UserSettings(user_id=user.id))
    db.commit()
    return user


def _file(db, user, drive_id, size=100, **kw):
    row = DriveFile(user_id=user.id, drive_id=drive_id, name=f"{drive_id}.pdf", mime_type="application/pdf",
                    extension=".pdf", category="pdf", size_bytes=size, **kw)
    db.add(row)
    db.commit()
    return row


def test_partial_trash_failure_keeps_successes_recorded(monkeypatch):
    fake = FakeDrive(fail_trash_on={"b"})
    monkeypatch.setattr(svc, "get_client", lambda user: fake)
    with SessionLocal() as db:
        user = _real_user(db)
        group = DuplicateGroup(user_id=user.id, match_level="hash", recommended_keep_drive_id="keep")
        db.add(group)
        db.flush()
        for drive_id in ("keep", "a", "b", "c"):
            _file(db, user, drive_id, duplicate_group_id=group.id)
        db.refresh(group)

        results = svc.trash_duplicate_group(db, user, group, "keep")
        assert [r["success"] for r in results] == [True, False, True]
        assert fake.trashed == ["a", "c"]

        # A fresh session sees exactly what happened on "Drive".
        with SessionLocal() as check:
            rows = {r.drive_id: r.is_trashed for r in check.query(DriveFile).filter_by(user_id=user.id)}
            assert rows == {"keep": False, "a": True, "b": False, "c": True}
            statuses = {a.file_drive_id: a.status for a in check.query(OptimizationAction).filter_by(user_id=user.id)}
            assert statuses == {"a": "success", "b": "failed", "c": "success"}


def test_real_compression_updates_in_place_and_restores_original(monkeypatch):
    import io

    import pikepdf

    pdf = pikepdf.new()
    for _ in range(40):
        pdf.add_blank_page(page_size=(200, 200))
    buf = io.BytesIO()
    pdf.save(buf, compress_streams=False, object_stream_mode=pikepdf.ObjectStreamMode.disable)
    original = buf.getvalue()

    fake = FakeDrive()
    fake.contents["doc1"] = original
    monkeypatch.setattr(svc, "get_client", lambda user: fake)
    with SessionLocal() as db:
        user = _real_user(db)
        user.settings.min_saving_percent = 1
        row = _file(db, user, "doc1", size=len(original))

        result = svc.compress_file(db, user, row)
        assert result["success"], result["message"]
        assert row.drive_id == "doc1"  # same file: links and sharing survive
        assert len(fake.contents["doc1"]) < len(original)

        action = db.query(OptimizationAction).filter_by(user_id=user.id, action="compressed").one()
        assert action.revision_id == "rev0" and action.restorable
        # Drive keeps the original "forever", so CloudClean schedules its deletion (30 days, for Undo).
        assert action.can_free_space and action.original_delete_at is not None
        assert "still uses" in result["message"]
        svc.restore_action(db, user, action)
        assert fake.contents["doc1"] == original
        assert row.size_bytes == len(original) and action.status == "reverted"
        # The old original is now a duplicate of the restored file: deleted, so storage isn't doubled.
        assert fake.deleted_revisions == {"rev0"} and action.original_delete_at is None


def _compressed(monkeypatch, db, drive_id, keep_forever=True):
    import io as _io

    import pikepdf

    pdf = pikepdf.new()
    for _ in range(40):
        pdf.add_blank_page(page_size=(200, 200))
    buf = _io.BytesIO()
    pdf.save(buf, compress_streams=False, object_stream_mode=pikepdf.ObjectStreamMode.disable)
    fake = FakeDrive(keep_forever=keep_forever)
    fake.contents[drive_id] = buf.getvalue()
    monkeypatch.setattr(svc, "get_client", lambda user: fake)
    user = _real_user(db)
    user.settings.min_saving_percent = 1
    svc.compress_file(db, user, _file(db, user, drive_id, size=len(buf.getvalue())))
    action = db.query(OptimizationAction).filter_by(user_id=user.id, action="compressed").one()
    return fake, user, action


def test_free_space_now_deletes_the_kept_original(monkeypatch):
    with SessionLocal() as db:
        fake, user, action = _compressed(monkeypatch, db, "doc-free")
        result = svc.free_original_space(db, user, action)
        assert result["success"] and fake.deleted_revisions == {"rev0"}
        assert not action.can_free_space and not action.restorable  # no Undo after this
        assert "Undo is no longer possible" in action.detail


def test_worker_deletes_originals_after_the_undo_window(monkeypatch):
    from datetime import datetime, timedelta

    with SessionLocal() as db:
        fake, user, action = _compressed(monkeypatch, db, "doc-expire")
        assert svc.delete_expired_originals(db) == 0 or "rev0" not in fake.deleted_revisions  # not due yet
        action.original_delete_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        assert svc.delete_expired_originals(db) >= 1
        db.refresh(action)
        assert "rev0" in fake.deleted_revisions and not action.can_free_space


def test_free_space_now_via_history_api_in_demo(demo):
    candidate = demo.get("/api/compression/candidates").json()[0]
    demo.post(f"/api/compression/{candidate['file_id']}")
    entry = next(h for h in demo.get("/api/history").json() if h["action"] == "compressed")
    assert entry["can_free_space"] and entry["original_delete_at"]
    r = demo.post(f"/api/history/{entry['id']}/free-space")
    assert r.status_code == 200 and "freed" in r.json()["message"]
    entry = next(h for h in demo.get("/api/history").json() if h["id"] == entry["id"])
    assert not entry["can_free_space"] and not entry["restorable"]
    assert demo.post(f"/api/history/{entry['id']}/free-space").status_code == 400


def test_original_not_kept_forever_is_left_to_drive(monkeypatch):
    with SessionLocal() as db:
        fake, user, action = _compressed(monkeypatch, db, "doc-api-upload", keep_forever=False)
        assert action.restorable and not action.can_free_space and action.original_delete_at is None
        assert "doesn't count toward your storage" in action.detail


def test_animated_image_is_skipped_untouched_and_not_suggested_again(monkeypatch):
    import io

    from PIL import Image

    frames = [Image.new("RGB", (300, 200), color=(60 * i, 100, 160)) for i in range(4)]
    buf = io.BytesIO()
    frames[0].save(buf, format="PNG", save_all=True, append_images=frames[1:], duration=120, compress_level=0)
    original = buf.getvalue()

    fake = FakeDrive()
    fake.contents["anim"] = original
    monkeypatch.setattr(svc, "get_client", lambda user: fake)
    with SessionLocal() as db:
        user = _real_user(db)
        user.settings.min_saving_percent = 1
        row = DriveFile(user_id=user.id, drive_id="anim", name="loader.png", mime_type="image/png", extension=".png",
                        category="images", size_bytes=len(original), estimated_savings_bytes=1000,
                        recommendation_type="compress")
        db.add(row)
        db.commit()

        result = svc.compress_file(db, user, row)
        assert result["success"] is False and "first frame" in result["message"]
        assert fake.contents["anim"] == original and not fake.revisions  # nothing uploaded
        assert row.recommendation_type == "already_optimized" and row.estimated_savings_bytes == 0
        action = db.query(OptimizationAction).filter_by(user_id=user.id).one()
        assert action.status == "skipped" and "first frame" in action.detail

"""Linked accounts: school/work (pooled) storage numbers, and the Duplicates,
Organize and Compression pages covering every linked account — each finding
labelled with its account, each action run in (and recorded by) the account
that owns the file."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal, init_db
from app.integrations.google_drive import is_organization_account, quota_from_about
from app.main import app
from app.models import StorageSnapshot, User, UserSettings
from app.services import drive_service
from app.services.account_service import account_summary
from app.services.storage_service import storage_overview

init_db()
GB = 1024 ** 3


# ---- school/work accounts on shared (pooled) storage -----------------------

def test_pooled_quota_counts_only_the_persons_own_drive():
    about = {"limit": str(116212 * GB), "usage": str(102746 * GB), "usageInDrive": str(3 * GB),
             "usageInDriveTrash": str(GB // 2)}
    pooled = quota_from_about(about, pooled=True)
    assert pooled["used_bytes"] == 3 * GB and pooled["quota_bytes"] == 0 and pooled["pooled"]
    assert pooled["drive_trash_bytes"] == GB // 2 and pooled["gmail_photos_bytes"] == 0
    assert (pooled["org_used_bytes"], pooled["org_quota_bytes"]) == (102746 * GB, 116212 * GB)

    personal = quota_from_about({"usage": str(7 * GB), "usageInDrive": str(6 * GB)})
    assert personal["quota_bytes"] == 15 * GB and personal["gmail_photos_bytes"] == GB and not personal["pooled"]


def test_organization_accounts_are_recognised():
    assert is_organization_account(User(email="a@vit.edu", hosted_domain="vit.edu"))
    assert not is_organization_account(User(email="a@outlook.com", hosted_domain=""))  # personal, non-Gmail address
    assert is_organization_account(User(email="a@vit.edu", hosted_domain=None))  # signed in before "hd" was kept
    assert not is_organization_account(User(email="a@gmail.com", hosted_domain=None))


def _linked_real_users(db, *emails):
    key = uuid.uuid4().hex
    users = []
    for email in emails:
        u = User(email=email, is_demo=False, refresh_token="r", profile_key=key)
        db.add(u)
        db.flush()
        db.add(UserSettings(user_id=u.id))
        users.append(u)
    db.commit()
    return users


def test_shared_school_storage_is_not_added_to_your_totals():
    with SessionLocal() as db:
        personal, school = _linked_real_users(db, f"p-{uuid.uuid4().hex[:6]}@gmail.com", f"s-{uuid.uuid4().hex[:6]}@vit.edu")
        db.add(StorageSnapshot(user_id=personal.id, used_bytes=7 * GB, quota_bytes=15 * GB, drive_bytes=6 * GB))
        db.add(StorageSnapshot(user_id=school.id, used_bytes=3 * GB, quota_bytes=0, drive_bytes=3 * GB, pooled=True,
                               org_used_bytes=102746 * GB, org_quota_bytes=116212 * GB))
        db.commit()

        combined = account_summary(db, personal, True)["combined"]
        assert combined["used_bytes"] == 10 * GB  # both people's own usage
        assert combined["quota_bytes"] == 15 * GB and combined["free_bytes"] == 8 * GB  # the college pool isn't yours
        assert combined["pooled_accounts"] == 1 and combined["scanned_accounts"] == 2

        overview = storage_overview(db, school)
        assert overview["pooled"] and overview["used_bytes"] == 3 * GB and overview["used_percent"] == 0.0


class SchoolDrive:
    def storage_quota(self, pooled=False):
        return quota_from_about({"limit": str(116212 * GB), "usage": str(102746 * GB),
                                 "usageInDrive": str(2 * GB)}, pooled)

    def iter_all_files(self):
        yield {"id": "s1", "name": "notes.pdf", "mimeType": "application/pdf", "size": str(GB), "md5Checksum": "n"}


def test_scanning_a_school_account_records_its_own_usage(monkeypatch):
    monkeypatch.setattr(drive_service, "get_client", lambda user: SchoolDrive())
    with SessionLocal() as db:
        (school,) = _linked_real_users(db, f"s-{uuid.uuid4().hex[:6]}@vit.edu")
        school.hosted_domain = "vit.edu"
        db.commit()
        drive_service.run_analysis(db, school)
        snap = db.query(StorageSnapshot).filter_by(user_id=school.id).one()
        assert snap.pooled and snap.used_bytes == 2 * GB and snap.quota_bytes == 0
        assert snap.org_used_bytes == 102746 * GB


# ---- every page covers every linked account (Demo Mode, three accounts) ----

@pytest.fixture
def profile():
    client = TestClient(app)
    client.post("/auth/demo")
    client.post("/api/accounts/simulated")
    client.post("/api/accounts/simulated")
    client.post("/api/accounts/scan")
    accounts = client.get("/api/accounts").json()
    return client, accounts["active_id"], {a["id"]: a["email"] for a in accounts["accounts"]}


def _history_of(client, account_id, active_id):
    """That account's History (the account filter), checked against switching to it."""
    rows = client.get("/api/history", params={"account_id": account_id}).json()
    assert all(h["account_id"] == account_id for h in rows)
    client.post(f"/api/accounts/{account_id}/switch")
    try:
        assert [h["id"] for h in client.get("/api/history", params={"account_id": account_id}).json()] == [h["id"] for h in rows]
        return rows
    finally:
        client.post(f"/api/accounts/{active_id}/switch")


def test_duplicates_cover_every_account_with_each_files_account(profile):
    client, active_id, emails = profile
    groups = client.get("/api/duplicates").json()
    cross = [g for g in groups if g["kind"] == "cross_account"]
    assert cross and all(len({f["account_id"] for f in g["files"]}) >= 2 for g in cross)
    assert all(f["account_email"] == emails[f["account_id"]] for g in groups for f in g["files"])
    assert any(g["kind"] == "account" and g["account_id"] != active_id for g in groups)  # another account's own group
    # Identical copies are listed once: in the cross-account group, not again per account.
    cross_content = {(g["files"][0]["content_hash"], g["files"][0]["size_bytes"]) for g in cross}
    assert not [g for g in groups if g["kind"] == "account" and g["match_level"] == "hash"
                and (g["files"][0]["content_hash"], g["files"][0]["size_bytes"]) in cross_content]


def test_trashing_another_accounts_duplicates_happens_in_that_account(profile):
    client, active_id, emails = profile
    group = next(g for g in client.get("/api/duplicates").json() if g["kind"] == "account" and g["account_id"] != active_id)
    res = client.post(f"/api/duplicates/{group['id']}/trash", json={
        "keep_drive_id": group["recommended_keep_drive_id"], "acknowledge_different_content": True})
    assert res.status_code == 200 and res.json()["account_id"] == group["account_id"]
    assert [h for h in _history_of(client, group["account_id"], active_id) if h["action"] == "trashed"]
    mine = client.get("/api/history", params={"account_id": active_id}).json()
    assert not [h for h in mine if h["action"] == "trashed"]  # not in the active one

    stranger = TestClient(app)
    stranger.post("/auth/demo")
    assert stranger.post(f"/api/duplicates/{group['id']}/trash",
                         json={"keep_drive_id": group["recommended_keep_drive_id"]}).status_code == 404


def test_organize_and_compression_act_in_the_owning_account(profile):
    client, active_id, emails = profile

    suggestion = next(s for s in client.get("/api/organize").json() if s["account_id"] != active_id)
    res = client.post(f"/api/organize/{suggestion['id']}/apply", json={})
    assert res.status_code == 200 and res.json()["account_id"] == suggestion["account_id"]
    assert [h for h in _history_of(client, suggestion["account_id"], active_id) if h["action"] == "organized"]

    candidate = next(c for c in client.get("/api/compression/candidates").json() if c["account_id"] != active_id)
    res = client.post(f"/api/compression/{candidate['file_id']}")
    assert res.status_code == 200 and res.json()["account_email"] == emails[candidate["account_id"]]
    assert [h for h in _history_of(client, candidate["account_id"], active_id) if h["action"] == "compressed"]

    video = next(c for c in client.get("/api/compression/video-candidates").json()["candidates"]
                 if c["account_id"] != active_id)
    job = client.post(f"/api/compression/{video['file_id']}/video").json()
    assert job["status"] == "done" and job["account_id"] == video["account_id"]
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "done"  # pollable from the active account

    stranger = TestClient(app)
    stranger.post("/auth/demo")
    assert stranger.post(f"/api/compression/{candidate['file_id']}").status_code == 404
    assert stranger.post(f"/api/organize/{suggestion['id']}/apply", json={}).status_code == 400

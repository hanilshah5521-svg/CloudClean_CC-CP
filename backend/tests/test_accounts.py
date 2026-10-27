"""Several Google accounts linked into one profile: adding, switching,
scanning each, duplicates spread across accounts, and profile isolation."""
import uuid
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import init_db
from app.integrations import google_drive
from app.main import app

init_db()
GB = 1024 ** 3


def _demo_profile(extra=2):
    c = TestClient(app)
    assert c.post("/auth/demo").status_code == 200
    c.post("/api/analyze")
    for _ in range(extra):
        assert c.post("/api/accounts/simulated").status_code == 200
    return c


def test_demo_profile_links_simulated_accounts_and_scans_each():
    c = _demo_profile()
    r = c.post("/api/accounts/simulated")
    assert r.status_code == 400 and "at most" in r.json()["detail"]

    summary = c.get("/api/accounts").json()
    accounts = summary["accounts"]
    assert len(accounts) == 3 and sum(a["active"] for a in accounts) == 1
    assert all(a["used_bytes"] and a["files"] for a in accounts)  # each one was scanned
    assert summary["combined"]["quota_bytes"] == 3 * 15 * GB and not summary["can_add"]

    scans = c.post("/api/accounts/scan").json()
    assert {s["account_id"] for s in scans} == {a["id"] for a in accounts}
    assert all(s["job"]["status"] == "done" for s in scans)  # demo jobs run inline
    assert c.get("/api/accounts/scan").json() == []  # nothing left running


def test_cross_account_duplicates_are_found_and_removed_in_their_own_accounts():
    c = _demo_profile()
    accounts = {a["id"]: a for a in c.get("/api/accounts").json()["accounts"]}
    data = c.get("/api/accounts/duplicates").json()
    assert data["groups"] and data["removable_bytes"] > 0
    for g in data["groups"]:
        assert len({f["account_id"] for f in g["files"]}) >= 2
        assert len({f["size_bytes"] for f in g["files"]}) == 1

    # The default keeps the copy in the account with the most free space.
    free = {aid: a["quota_bytes"] - a["used_bytes"] for aid, a in accounts.items()}
    group = data["groups"][0]
    keep = next(f for f in group["files"] if f["id"] == group["recommended_keep_id"])
    assert free[keep["account_id"]] == max(free[f["account_id"]] for f in group["files"])

    some_account = group["files"][0]["account_id"]
    filtered = c.get("/api/accounts/duplicates", params={"account_id": some_account}).json()["groups"]
    assert filtered and all(some_account in {f["account_id"] for f in g["files"]} for g in filtered)

    remove = [f for f in group["files"] if f["id"] != keep["id"]]
    results = c.post("/api/accounts/duplicates/remove",
                     json={"keep_file_id": keep["id"], "remove_file_ids": [f["id"] for f in remove]}).json()["results"]
    assert all(r["success"] for r in results)
    assert {r["account_email"] for r in results} == {f["account_email"] for f in remove}
    assert group["key"] not in {g["key"] for g in c.get("/api/accounts/duplicates").json()["groups"]}

    # The removal is in the History of the account that owned the copy, so Restore works there.
    owner = remove[0]["account_id"]
    c.post(f"/api/accounts/{owner}/switch")
    history = c.get("/api/history").json()
    assert any(h["action"] == "trashed" and h["file_name"] == remove[0]["name"] and "is kept in" in h["detail"]
               for h in history)


def test_only_identical_copies_can_be_removed():
    c = _demo_profile(extra=1)
    group = c.get("/api/accounts/duplicates").json()["groups"][0]
    other = c.get("/api/accounts/duplicates").json()["groups"][1]
    r = c.post("/api/accounts/duplicates/remove",
               json={"keep_file_id": group["files"][0]["id"], "remove_file_ids": [other["files"][0]["id"]]})
    assert r.status_code == 400 and "identical" in r.json()["detail"]


def test_profiles_are_isolated():
    a, b = _demo_profile(extra=1), _demo_profile(extra=1)
    b_accounts = b.get("/api/accounts").json()["accounts"]
    b_id = b_accounts[0]["id"]
    assert a.post(f"/api/accounts/{b_id}/switch").status_code == 404
    assert a.delete(f"/api/accounts/{b_id}").status_code == 404
    b_job = b.post("/api/accounts/scan").json()[0]["job"]["id"]
    assert a.get(f"/api/jobs/{b_job}").status_code == 404
    b_file = b.get("/api/accounts/duplicates").json()["groups"][0]["files"]
    r = a.post("/api/accounts/duplicates/remove",
               json={"keep_file_id": b_file[0]["id"], "remove_file_ids": [b_file[1]["id"]]})
    assert r.status_code == 400


def test_switching_and_removing_accounts():
    c = _demo_profile()
    accounts = c.get("/api/accounts").json()["accounts"]
    active = next(a for a in accounts if a["active"])
    other = next(a for a in accounts if not a["active"])
    assert c.delete(f"/api/accounts/{active['id']}").status_code == 400  # switch away first

    assert c.post(f"/api/accounts/{other['id']}/switch").json()["active_id"] == other["id"]
    assert c.get("/api/user").json()["email"] == other["email"]
    assert c.get("/api/analysis").json()["analyzed"]  # pages now show that account's data

    for a in accounts:
        if a["id"] != other["id"]:
            assert c.delete(f"/api/accounts/{a['id']}").status_code == 200
    remaining = c.get("/api/accounts").json()["accounts"]
    assert [a["id"] for a in remaining] == [other["id"]]
    assert c.get("/api/accounts/duplicates").json()["groups"] == []


def test_adding_a_google_account_links_it_and_keeps_the_current_one(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "client-id")
    monkeypatch.setattr(settings, "google_client_secret", "client-secret")
    suffix = uuid.uuid4().hex[:6]
    who = {"id": f"g-main-{suffix}", "email": f"main-{suffix}@example.com"}

    class Creds:
        token, refresh_token, expiry = "access", "refresh", datetime(2030, 1, 1)

    monkeypatch.setattr("app.api.routes.auth.exchange_code", lambda code, state, verifier: (Creds(), google_drive.BASE_SCOPES))
    monkeypatch.setattr("app.api.routes.auth.fetch_userinfo", lambda creds: {**who, "name": "N"})

    c = TestClient(app)
    login = c.get("/auth/google/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    c.get("/auth/callback", params={"code": "c1", "state": state}, follow_redirects=False)
    main_email = c.get("/api/user").json()["email"]

    who.update(id=f"g-college-{suffix}", email=f"college-{suffix}@example.edu")
    link = c.get("/auth/google/link", follow_redirects=False)
    query = parse_qs(urlparse(link.headers["location"]).query)
    assert "select_account" in query["prompt"][0]  # Google's account chooser, not the signed-in account
    r = c.get("/auth/callback", params={"code": "c2", "state": query["state"][0]}, follow_redirects=False)
    assert r.headers["location"].endswith(f"/accounts?linked={who['email'].replace('@', '%40')}")

    assert c.get("/api/user").json()["email"] == main_email  # still working in the same account
    emails = {a["email"] for a in c.get("/api/accounts").json()["accounts"]}
    assert emails == {main_email, who["email"]}

    # Signing in later with the linked account opens the same profile.
    fresh = TestClient(app)
    login = fresh.get("/auth/google/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    fresh.get("/auth/callback", params={"code": "c3", "state": state}, follow_redirects=False)
    assert {a["email"] for a in fresh.get("/api/accounts").json()["accounts"]} == emails


def test_demo_profiles_cannot_link_google_accounts():
    c = _demo_profile(extra=0)
    r = c.get("/auth/google/link", follow_redirects=False)
    assert r.headers["location"].endswith("/accounts?error=demo_link")

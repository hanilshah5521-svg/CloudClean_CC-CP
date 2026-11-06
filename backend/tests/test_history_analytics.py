"""History and Analytics over every linked account: rows are labelled with
their account, totals come from the whole stored History (so they survive
restarts and re-scans), and Undo runs in the account the change was made in."""
import pytest
from fastapi.testclient import TestClient

from app.core.database import engine, init_db
from app.main import app

init_db()


@pytest.fixture
def profile():
    client = TestClient(app)
    client.post("/auth/demo")
    client.post("/api/accounts/simulated")
    client.post("/api/accounts/scan")
    accounts = client.get("/api/accounts").json()
    other = next(a["id"] for a in accounts["accounts"] if a["id"] != accounts["active_id"])
    return client, accounts["active_id"], other


def _compress_one_in(client, account_id):
    candidate = next(c for c in client.get("/api/compression/candidates").json() if c["account_id"] == account_id)
    res = client.post(f"/api/compression/{candidate['file_id']}").json()
    assert res["success"]
    return res


def test_history_lists_every_account_and_filters_by_one(profile):
    client, active_id, other = profile
    _compress_one_in(client, active_id)
    _compress_one_in(client, other)

    rows = client.get("/api/history").json()
    assert {h["account_id"] for h in rows} == {active_id, other}
    assert all(h["account_email"] for h in rows)
    only_other = client.get("/api/history", params={"account_id": other}).json()
    assert only_other and {h["account_id"] for h in only_other} == {other}

    stranger = TestClient(app)
    stranger.post("/auth/demo")
    assert stranger.get("/api/history", params={"account_id": other}).status_code == 404


def test_summary_totals_survive_a_restart_and_exclude_undone_actions(profile):
    client, active_id, other = profile
    a = _compress_one_in(client, active_id)
    b = _compress_one_in(client, other)

    summary = client.get("/api/history/summary").json()
    assert summary["saved_bytes"] == a["saved_bytes"] + b["saved_bytes"] > 0
    assert summary["by_action"]["compressed"]["count"] == 2
    per_account = {x["account_id"]: x["saved_bytes"] for x in summary["by_account"]}
    assert per_account == {active_id: a["saved_bytes"], other: b["saved_bytes"]}
    assert summary["timeline"][-1]["cumulative_bytes"] == summary["saved_bytes"]

    # A restart is a new process: new database connections, same database file.
    engine.dispose()
    again = TestClient(app, cookies=client.cookies)
    assert again.get("/api/history/summary").json()["saved_bytes"] == summary["saved_bytes"]
    # A re-scan rebuilds the file list but keeps History.
    again.post("/api/accounts/scan")
    assert again.get("/api/history/summary").json()["saved_bytes"] == summary["saved_bytes"]

    # Undo another account's compression from here: it runs there and stops counting.
    entry = next(h for h in again.get("/api/history", params={"account_id": other}).json() if h["action"] == "compressed")
    res = again.post(f"/api/history/{entry['id']}/restore")
    assert res.status_code == 200 and res.json()["account_id"] == other
    after = again.get("/api/history/summary").json()
    assert after["saved_bytes"] == a["saved_bytes"]
    assert again.get("/api/history/summary", params={"account_id": other}).json()["saved_bytes"] == 0


def test_analytics_cover_all_accounts_or_one(profile):
    client, active_id, other = profile
    every = client.get("/api/analytics/breakdown").json()
    mine = client.get("/api/analytics/breakdown", params={"account_id": active_id}).json()
    theirs = client.get("/api/analytics/breakdown", params={"account_id": other}).json()
    count = lambda b: sum(c["count"] for c in b["by_category"])  # noqa: E731
    assert count(every) == count(mine) + count(theirs) > 0
    assert {f["account_email"] for f in every["largest_files"]} <= {f["account_email"] for f in mine["largest_files"] + theirs["largest_files"]}
    # Copies spread over both accounts count once, as on the Duplicates page.
    duplicates = client.get("/api/duplicates").json()
    assert every["duplicate_storage_bytes"] == sum(g["potential_recovery_bytes"] for g in duplicates)

    history = client.get("/api/analytics/history", params={"range": "all"}).json()
    one = client.get("/api/analytics/history", params={"range": "all", "account_id": active_id}).json()
    assert history["points"][-1]["used_bytes"] >= one["points"][-1]["used_bytes"] > 0
    assert client.get("/api/analytics/breakdown", params={"account_id": 10 ** 9}).status_code == 404

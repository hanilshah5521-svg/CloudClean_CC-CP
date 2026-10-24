"""S3 workflows through the HTTP API: Demo Mode (simulated account) and the
real boto3 code path against moto's in-process AWS mock."""
import io

import pytest
from fastapi.testclient import TestClient

from app.core.database import init_db
from app.main import app

init_db()

MB = 1024 * 1024


def _client():
    c = TestClient(app)
    assert c.post("/auth/demo").status_code == 200
    return c


@pytest.fixture
def demo():
    c = _client()
    assert c.post("/api/s3/connect-demo").status_code == 200
    r = c.post("/api/s3/scan")
    assert r.status_code == 200, r.text
    return c


def test_s3_requires_a_connection():
    c = _client()
    assert c.get("/api/s3").json()["connected"] is False
    assert c.post("/api/s3/scan").status_code == 400


def test_demo_scan_finds_each_kind_of_waste(demo):
    o = demo.get("/api/s3").json()
    assert o["connected"] and o["is_demo"] and o["monthly_cost_usd"] > 0
    kinds = {r["type"] for r in o["recommendations"]}
    assert {"tiering", "noncurrent", "abort_uploads", "duplicates", "compress"} <= kinds
    assert all(r["reason"] for r in o["recommendations"])
    assert o["potential_monthly_saving_usd"] <= o["monthly_cost_usd"]


def test_applying_lifecycle_rules_lowers_cost_and_undo_removes_only_our_rule(demo):
    before = demo.get("/api/s3").json()
    site = next(b for b in before["buckets"] if b["name"] == "acme-static-site")
    assert site["lifecycle_rule_count"] == 1  # the user's own rule

    for rec in before["recommendations"]:
        if rec["action"] == "apply_lifecycle":
            preview = demo.get(f"/api/s3/recommendations/{rec['id']}/preview").json()
            assert preview["rule"] in preview["resulting_configuration"]["Rules"]
            assert demo.post(f"/api/s3/recommendations/{rec['id']}/apply").status_code == 200
    after = demo.post("/api/s3/scan").json()
    assert after["monthly_cost_usd"] < before["monthly_cost_usd"] * 0.6
    assert "DEEP_ARCHIVE" in after["bytes_by_class"] and "GLACIER_IR" in after["bytes_by_class"]

    # Applying the same recommendation twice is refused.
    applied = next(r for r in before["recommendations"] if r["action"] == "apply_lifecycle")
    assert demo.post(f"/api/s3/recommendations/{applied['id']}/apply").status_code == 400

    history = demo.get("/api/s3/history").json()
    rule_added = next(h for h in history if h["action"] == "lifecycle_rule_added" and h["bucket"] == "acme-app-logs")
    r = demo.post(f"/api/s3/history/{rule_added['id']}/undo")
    assert r.status_code == 200 and "stay in their" in r.json()["message"]


def test_duplicate_removal_in_unversioned_bucket_uses_trash_prefix_and_undo(demo):
    group = demo.get("/api/s3/duplicates").json()[0]
    assert not group["versioned"]
    keep = group["recommended_keep_id"]
    res = demo.post("/api/s3/duplicates/trash",
                    json={"bucket_id": group["bucket_id"], "group": group["group"], "keep_object_id": keep}).json()
    assert all(r["success"] for r in res["results"])

    history = demo.get("/api/s3/history").json()
    assert any(h["target"] == "cloudclean-trash-expiry" for h in history)  # S3 empties the trash after 30 days
    trashed = next(h for h in history if h["action"] == "trashed")
    assert "cloudclean-trash/" in trashed["detail"]

    after = demo.post("/api/s3/scan").json()
    remaining = {x["key"] for g in demo.get("/api/s3/duplicates").json() for x in g["objects"]}
    assert trashed["target"] not in remaining
    assert demo.post(f"/api/s3/history/{trashed['id']}/undo").status_code == 200
    rescanned = demo.post("/api/s3/scan").json()
    assert rescanned["total_bytes"] == after["total_bytes"]  # moved back out of the trash prefix


def test_keep_must_belong_to_the_group(demo):
    groups = demo.get("/api/s3/duplicates").json()
    other = groups[1]["objects"][0]["id"]
    r = demo.post("/api/s3/duplicates/trash",
                  json={"bucket_id": groups[0]["bucket_id"], "group": groups[0]["group"], "keep_object_id": other})
    assert r.status_code == 400


def test_compression_is_undoable(demo):
    cand = demo.get("/api/s3/compression").json()[0]
    res = demo.post(f"/api/s3/objects/{cand['id']}/compress").json()
    assert res["success"] and res["new_size_bytes"] < res["original_size_bytes"]
    action = next(h for h in demo.get("/api/s3/history").json() if h["action"] == "compressed")
    assert action["restorable"]
    assert demo.post(f"/api/s3/history/{action['id']}/undo").status_code == 200


def test_iam_policy_is_least_privilege():
    actions = {a for st in TestClient(app).get("/api/s3/iam-policy").json()["Statement"] for a in st["Action"]}
    assert "s3:PutLifecycleConfiguration" in actions
    assert not any(a in actions for a in ("s3:*", "s3:DeleteBucket", "s3:PutBucketPolicy"))


# ---------------------------------------------------------- real boto3 path (moto)

moto = pytest.importorskip("moto")


@pytest.fixture
def aws(monkeypatch):
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    with moto.mock_aws():
        import boto3
        yield boto3.client("s3", region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")


def _connect_real(c):
    r = c.post("/api/s3/connect", json={"access_key_id": "AKIATESTTESTTEST1234",
                                         "secret_access_key": "testsecrettestsecrettestsecret", "region": "us-east-1"})
    assert r.status_code == 200, r.text
    return r.json()


def _big_pdf() -> bytes:
    import pikepdf

    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.pages[0].Contents = pdf.make_stream(b"0 0 m 10 10 l S\n" * 90_000)
    buf = io.BytesIO()
    pdf.save(buf, compress_streams=False, object_stream_mode=pikepdf.ObjectStreamMode.disable)
    return buf.getvalue()


def test_real_scan_merges_lifecycle_and_moves_duplicates_to_trash(aws):
    aws.create_bucket(Bucket="cc-real")
    aws.put_bucket_lifecycle_configuration(Bucket="cc-real", LifecycleConfiguration={"Rules": [
        {"ID": "user-tmp-cleanup", "Status": "Enabled", "Filter": {"Prefix": "tmp/"}, "Expiration": {"Days": 3}}]})
    body = b"x" * (2 * MB)
    aws.put_object(Bucket="cc-real", Key="data/report.bin", Body=body)
    aws.put_object(Bucket="cc-real", Key="data/old/report-copy.bin", Body=body)
    upload = aws.create_multipart_upload(Bucket="cc-real", Key="exports/big.tar")
    aws.upload_part(Bucket="cc-real", Key="exports/big.tar", UploadId=upload["UploadId"], PartNumber=1, Body=b"p" * MB)

    c = _client()
    assert _connect_real(c)["account_id"]
    o = c.post("/api/s3/scan").json()
    bucket = next(b for b in o["buckets"] if b["name"] == "cc-real")
    assert bucket["incomplete_upload_count"] == 1 and bucket["incomplete_upload_bytes"] == MB

    abort = next(r for r in o["recommendations"] if r["type"] == "abort_uploads")
    assert c.post(f"/api/s3/recommendations/{abort['id']}/apply").status_code == 200
    ids = {r["ID"] for r in aws.get_bucket_lifecycle_configuration(Bucket="cc-real")["Rules"]}
    assert ids == {"user-tmp-cleanup", "cloudclean-abort-incomplete-uploads"}  # the user's rule survived

    group = c.get("/api/s3/duplicates").json()[0]
    keep = next(x for x in group["objects"] if x["key"] == "data/report.bin")
    res = c.post("/api/s3/duplicates/trash", json={"bucket_id": group["bucket_id"], "group": group["group"],
                                                   "keep_object_id": keep["id"]}).json()
    assert res["results"][0]["success"], res
    keys = {x["Key"] for x in aws.list_objects_v2(Bucket="cc-real")["Contents"]}
    assert "data/old/report-copy.bin" not in keys
    assert any(k.startswith("cloudclean-trash/") and k.endswith("data/old/report-copy.bin") for k in keys)
    ids = {r["ID"] for r in aws.get_bucket_lifecycle_configuration(Bucket="cc-real")["Rules"]}
    assert "cloudclean-trash-expiry" in ids and "user-tmp-cleanup" in ids

    history = c.get("/api/s3/history").json()
    trashed = next(h for h in history if h["action"] == "trashed")
    assert c.post(f"/api/s3/history/{trashed['id']}/undo").status_code == 200
    keys = {x["Key"] for x in aws.list_objects_v2(Bucket="cc-real")["Contents"]}
    assert "data/old/report-copy.bin" in keys and not any(k.startswith("cloudclean-trash/") for k in keys)

    added = next(h for h in history if h["target"] == "cloudclean-abort-incomplete-uploads")
    assert c.post(f"/api/s3/history/{added['id']}/undo").status_code == 200
    ids = {r["ID"] for r in aws.get_bucket_lifecycle_configuration(Bucket="cc-real")["Rules"]}
    assert "cloudclean-abort-incomplete-uploads" not in ids and "user-tmp-cleanup" in ids


def test_real_versioned_bucket_uses_delete_markers(aws):
    aws.create_bucket(Bucket="cc-versioned")
    aws.put_bucket_versioning(Bucket="cc-versioned", VersioningConfiguration={"Status": "Enabled"})
    body = b"y" * MB
    aws.put_object(Bucket="cc-versioned", Key="a.bin", Body=body)
    aws.put_object(Bucket="cc-versioned", Key="b/a-copy.bin", Body=body)
    aws.put_object(Bucket="cc-versioned", Key="a.bin", Body=body)  # one noncurrent version

    c = _client()
    _connect_real(c)
    o = c.post("/api/s3/scan").json()
    bucket = next(b for b in o["buckets"] if b["name"] == "cc-versioned")
    assert bucket["versioning"] == "Enabled" and bucket["noncurrent_count"] == 1

    group = c.get("/api/s3/duplicates").json()[0]
    keep = next(x for x in group["objects"] if x["key"] == "a.bin")
    c.post("/api/s3/duplicates/trash", json={"bucket_id": group["bucket_id"], "group": group["group"],
                                             "keep_object_id": keep["id"]})
    markers = aws.list_object_versions(Bucket="cc-versioned").get("DeleteMarkers", [])
    assert [m["Key"] for m in markers] == ["b/a-copy.bin"]

    trashed = next(h for h in c.get("/api/s3/history").json() if h["action"] == "trashed")
    c.post(f"/api/s3/history/{trashed['id']}/undo")
    assert not aws.list_object_versions(Bucket="cc-versioned").get("DeleteMarkers")


def test_real_compression_keeps_a_backup_and_restores_it(aws):
    original = _big_pdf()
    assert len(original) > MB
    aws.create_bucket(Bucket="cc-docs")
    aws.put_object(Bucket="cc-docs", Key="docs/manual.pdf", Body=original, ContentType="application/pdf")

    c = _client()
    _connect_real(c)
    c.post("/api/s3/scan")
    cand = next(x for x in c.get("/api/s3/compression").json() if x["key"] == "docs/manual.pdf")
    res = c.post(f"/api/s3/objects/{cand['id']}/compress").json()
    assert res["success"], res
    head = aws.head_object(Bucket="cc-docs", Key="docs/manual.pdf")
    assert head["ContentLength"] == res["new_size_bytes"] < len(original)
    assert head["ContentType"] == "application/pdf"

    action = next(h for h in c.get("/api/s3/history").json() if h["action"] == "compressed")
    c.post(f"/api/s3/history/{action['id']}/undo")
    restored = aws.get_object(Bucket="cc-docs", Key="docs/manual.pdf")["Body"].read()
    assert restored == original


def test_bad_credentials_are_reported_not_stored(aws, monkeypatch):
    from app.integrations import s3_client

    def reject(*a, **k):
        raise s3_client.S3AccessError("AWS InvalidClientTokenId: The security token included in the request is invalid")

    monkeypatch.setattr("app.services.s3_service.validate_credentials", reject)
    c = _client()
    r = c.post("/api/s3/connect", json={"access_key_id": "AKIABADBADBADBAD1234",
                                         "secret_access_key": "badbadbadbadbadbadbad", "region": "us-east-1"})
    assert r.status_code == 400 and "InvalidClientTokenId" in r.json()["detail"]
    assert c.get("/api/s3").json()["connected"] is False


def test_real_animated_image_is_skipped_and_left_unchanged(aws):
    from PIL import Image

    from app.core.database import SessionLocal
    from app.models.s3 import S3Object

    frames = [Image.new("RGB", (300, 200), color=(60 * i, 100, 160)) for i in range(4)]
    buf = io.BytesIO()
    frames[0].save(buf, format="WEBP", save_all=True, append_images=frames[1:], duration=120, lossless=True)
    original = buf.getvalue()
    aws.create_bucket(Bucket="cc-anim")
    aws.put_object(Bucket="cc-anim", Key="ui/spinner.webp", Body=original, ContentType="image/webp")

    c = _client()
    _connect_real(c)
    c.post("/api/s3/scan")
    with SessionLocal() as db:
        obj_id = db.query(S3Object).filter(S3Object.key == "ui/spinner.webp").order_by(S3Object.id.desc()).first().id

    res = c.post(f"/api/s3/objects/{obj_id}/compress").json()
    assert res["success"] is False and "first frame" in res["message"]
    assert aws.get_object(Bucket="cc-anim", Key="ui/spinner.webp")["Body"].read() == original
    skipped = next(h for h in c.get("/api/s3/history").json() if h["target"] == "ui/spinner.webp")
    assert skipped["status"] == "skipped"
    assert obj_id not in {x["id"] for x in c.get("/api/s3/compression").json()}

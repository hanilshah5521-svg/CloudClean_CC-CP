"""AWS S3 workflows: connect, scan, and safe, undoable optimizations.

Same rules as the Drive side (see optimization_service.py):
1. CloudClean never permanently deletes anything itself. Removing an object
   either adds a delete marker (versioned bucket: the data stays as a
   noncurrent version) or moves it to cloudclean-trash/, which an S3
   lifecycle rule empties after 30 days — the S3 equivalent of Drive's Trash.
2. Lifecycle changes are MERGED into the bucket's existing rules (S3's API
   replaces the whole configuration), and undo removes only CloudClean's rule.
3. Every change is recorded in S3Action with what's needed to undo it, and
   multi-object actions commit after each object.
"""
from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.analyzers.s3_rules import (
    TRASH_DAYS, TRASH_PREFIX, TRASH_RULE_ID, BucketScan, Pricing, S3Engine, default_keep, load_pricing, merge_rule,
)
from app.compression.images import UnsafeToCompress
from app.integrations.demo_s3 import generate_demo_state
from app.integrations.s3_client import (
    BotoCoreError, ClientError, ClientFactory, S3AccessError, bucket_region, describe_error, lifecycle_rules,
    list_all_versions, list_current_objects, list_incomplete_uploads, put_lifecycle_rules, validate_credentials,
    versioning_status,
)
from app.models import User
from app.models.s3 import S3Action, S3Bucket, S3Connection, S3Object, S3Recommendation

logger = logging.getLogger("cloudclean")

MAX_COMPRESS_BYTES = 200 * 1024 * 1024
AWS_ERRORS = (ClientError, BotoCoreError)


class S3Error(Exception):
    pass


# ----------------------------------------------------------------- connection

def get_connection(db: Session, user: User) -> S3Connection | None:
    return db.query(S3Connection).filter(S3Connection.user_id == user.id).first()


def _require_connection(db: Session, user: User) -> S3Connection:
    conn = get_connection(db, user)
    if conn is None:
        raise S3Error("Connect an AWS account (or start the S3 demo) first.")
    return conn


def connect(db: Session, user: User, access_key_id: str, secret_access_key: str, region: str) -> S3Connection:
    ident = validate_credentials(access_key_id.strip(), secret_access_key.strip(), region)
    disconnect(db, user)
    conn = S3Connection(user_id=user.id, is_demo=False, access_key_id=access_key_id.strip(),
                        secret_access_key=secret_access_key.strip(), region=region,
                        account_id=ident["account_id"], arn=ident["arn"])
    db.add(conn)
    db.commit()
    return conn


def connect_demo(db: Session, user: User) -> S3Connection:
    disconnect(db, user)
    conn = S3Connection(user_id=user.id, is_demo=True, region="us-east-1", account_id="123456789012",
                        arn="arn:aws:iam::123456789012:user/cloudclean-demo", demo_state=generate_demo_state())
    db.add(conn)
    db.commit()
    return conn


def disconnect(db: Session, user: User) -> None:
    """Forget the connection (and its keys) and the cached scan. History is kept."""
    for model in (S3Recommendation, S3Object, S3Bucket, S3Connection):
        db.query(model).filter(model.user_id == user.id).delete(synchronize_session=False)
    db.commit()


def _clients(conn: S3Connection) -> ClientFactory:
    def persist(state: dict):
        # Re-attach first: after a commit the attribute is expired, and
        # flag_modified needs it loaded. Then force the JSON column dirty,
        # since in-place dict changes aren't tracked.
        conn.demo_state = state
        flag_modified(conn, "demo_state")

    return ClientFactory(conn, on_demo_change=persist)


# ----------------------------------------------------------------- scan

def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _scan_bucket(client, name: str, region: str, now: datetime) -> BucketScan:
    versioning = versioning_status(client, name)
    rules = lifecycle_rules(client, name)
    objects, noncurrent = [], []
    if versioning:
        versions, markers, truncated = list_all_versions(client, name)
        by_key: dict[str, list[dict]] = {}
        for v in versions:
            by_key.setdefault(v["Key"], []).append({**v, "marker": False})
        for m in markers:
            by_key.setdefault(m["Key"], []).append({**m, "marker": True})
        for key, entries in by_key.items():
            entries.sort(key=lambda e: (e["LastModified"], e.get("IsLatest", False)), reverse=True)
            for i, e in enumerate(entries):
                if e["marker"]:
                    continue
                item = {"key": key, "size": e.get("Size", 0), "storage_class": e.get("StorageClass") or "STANDARD",
                        "etag": e.get("ETag", ""), "last_modified": _naive(e["LastModified"]),
                        "age_days": max(0, (now - e["LastModified"]).days)}
                if i == 0 and e.get("IsLatest", True):
                    objects.append(item)
                else:  # noncurrent since the next-newer entry was written
                    item["noncurrent_days"] = max(0, (now - entries[i - 1]["LastModified"]).days)
                    noncurrent.append(item)
    else:
        contents, truncated = list_current_objects(client, name)
        for c in contents:
            objects.append({"key": c["Key"], "size": c.get("Size", 0), "storage_class": c.get("StorageClass") or "STANDARD",
                            "etag": c.get("ETag", ""), "last_modified": _naive(c["LastModified"]),
                            "age_days": max(0, (now - c["LastModified"]).days)})
    uploads = [{**u, "age_days": max(0, (now - u["initiated"]).days)} for u in list_incomplete_uploads(client, name)]
    return BucketScan(name=name, region=region, versioning=versioning, rules=rules, objects=objects,
                      noncurrent=noncurrent, uploads=uploads, truncated=truncated)


def scan(db: Session, user: User) -> dict:
    conn = _require_connection(db, user)
    clients = _clients(conn)
    now = datetime.now(timezone.utc)
    try:
        buckets = clients().list_buckets().get("Buckets", [])
    except AWS_ERRORS as exc:
        raise S3AccessError(describe_error(exc)) from exc

    engine = S3Engine(min_saving_percent=user.settings.min_saving_percent)
    for model in (S3Recommendation, S3Object, S3Bucket):
        db.query(model).filter(model.user_id == user.id).delete(synchronize_session=False)
    db.flush()

    for b in buckets:
        name = b["Name"]
        try:
            region = bucket_region(clients(), name)
            data = _scan_bucket(clients(region), name, region, now)
        except AWS_ERRORS as exc:
            logger.warning("Scanning bucket %s failed: %s", name, exc)
            db.add(S3Bucket(user_id=user.id, name=name, scan_error=describe_error(exc)))
            continue
        recs, groups, compress = engine.analyze(data)
        by_class: dict[str, int] = {}
        for o in data.objects + data.noncurrent:
            by_class[o["storage_class"]] = by_class.get(o["storage_class"], 0) + o["size"]
        row = S3Bucket(
            user_id=user.id, name=name, region=region, versioning=data.versioning, lifecycle_rules=data.rules,
            object_count=len(data.objects), total_bytes=sum(by_class.values()) + sum(u["size"] for u in data.uploads),
            bytes_by_class=by_class, noncurrent_bytes=sum(v["size"] for v in data.noncurrent),
            noncurrent_count=len(data.noncurrent), incomplete_upload_bytes=sum(u["size"] for u in data.uploads),
            incomplete_upload_count=len(data.uploads),
            small_object_count=sum(1 for o in data.objects if o["size"] < 128 * 1024),
            monthly_cost_usd=engine.monthly_cost(data), truncated=data.truncated,
        )
        db.add(row)
        db.flush()
        for o in data.objects:
            db.add(S3Object(
                user_id=user.id, bucket_id=row.id, key=o["key"], size_bytes=o["size"], storage_class=o["storage_class"],
                last_modified=o["last_modified"], age_days=o["age_days"], etag=o["etag"],
                duplicate_group=groups.get(o["key"]), compress_saving_bytes=compress.get(o["key"], 0),
                is_trashed=o["key"].startswith(TRASH_PREFIX),
            ))
        for r in recs:
            db.add(S3Recommendation(
                user_id=user.id, bucket_id=row.id, type=r.type, action=r.action, title=r.title, reason=r.reason,
                saving_bytes=r.saving_bytes, monthly_saving_usd=r.monthly_saving_usd,
                one_time_cost_usd=r.one_time_cost_usd, risk=r.risk, confidence=r.confidence, payload=r.payload,
            ))
    conn.last_scan_at = now.replace(tzinfo=None)
    db.commit()
    return overview(db, user)


# ----------------------------------------------------------------- read models

def overview(db: Session, user: User) -> dict:
    conn = get_connection(db, user)
    pricing = load_pricing()
    if conn is None:
        return {"connected": False, "pricing_disclaimer": pricing["disclaimer"]}
    buckets = db.query(S3Bucket).filter(S3Bucket.user_id == user.id).order_by(S3Bucket.monthly_cost_usd.desc()).all()
    recs = (db.query(S3Recommendation)
            .filter(S3Recommendation.user_id == user.id, S3Recommendation.status == "pending")
            .order_by(S3Recommendation.monthly_saving_usd.desc()).all())
    names = {b.id: b.name for b in buckets}
    by_class: dict[str, int] = {}
    for b in buckets:
        for cls, size in (b.bytes_by_class or {}).items():
            by_class[cls] = by_class.get(cls, 0) + size
    return {
        "connected": True,
        "is_demo": conn.is_demo,
        "account_id": conn.account_id,
        "arn": conn.arn,
        "region": conn.region,
        "last_scan_at": conn.last_scan_at,
        "pricing_region": pricing["region"],
        "pricing_disclaimer": pricing["disclaimer"],
        "total_bytes": sum(b.total_bytes for b in buckets),
        "monthly_cost_usd": round(sum(b.monthly_cost_usd for b in buckets), 2),
        "potential_monthly_saving_usd": round(sum(r.monthly_saving_usd for r in recs), 2),
        "bytes_by_class": by_class,
        "buckets": [{
            "id": b.id, "name": b.name, "region": b.region, "versioning": b.versioning,
            "lifecycle_rule_count": len(b.lifecycle_rules or []), "object_count": b.object_count,
            "total_bytes": b.total_bytes, "bytes_by_class": b.bytes_by_class, "noncurrent_bytes": b.noncurrent_bytes,
            "noncurrent_count": b.noncurrent_count, "incomplete_upload_bytes": b.incomplete_upload_bytes,
            "incomplete_upload_count": b.incomplete_upload_count, "small_object_count": b.small_object_count,
            "monthly_cost_usd": b.monthly_cost_usd, "truncated": b.truncated, "scan_error": b.scan_error,
        } for b in buckets],
        "recommendations": [{
            "id": r.id, "bucket_id": r.bucket_id, "bucket": names.get(r.bucket_id, ""), "type": r.type,
            "action": r.action, "title": r.title, "reason": r.reason, "saving_bytes": r.saving_bytes,
            "monthly_saving_usd": r.monthly_saving_usd, "one_time_cost_usd": r.one_time_cost_usd,
            "risk": r.risk, "confidence": r.confidence,
        } for r in recs],
    }


def _bucket(db: Session, user: User, bucket_id: int) -> S3Bucket:
    b = db.query(S3Bucket).filter(S3Bucket.id == bucket_id, S3Bucket.user_id == user.id).first()
    if b is None:
        raise S3Error("Bucket not found. Run a new scan.")
    return b


def duplicate_groups(db: Session, user: User, bucket_id: int | None = None) -> list[dict]:
    q = db.query(S3Object).filter(S3Object.user_id == user.id, S3Object.duplicate_group.isnot(None),
                                  S3Object.is_trashed.is_(False))
    if bucket_id:
        q = q.filter(S3Object.bucket_id == bucket_id)
    groups: dict[tuple[int, int], list[S3Object]] = {}
    for o in q.all():
        groups.setdefault((o.bucket_id, o.duplicate_group), []).append(o)
    buckets = {b.id: b for b in db.query(S3Bucket).filter(S3Bucket.user_id == user.id)}
    engine = S3Engine()
    out = []
    for (bid, gid), objs in groups.items():
        if len(objs) < 2:
            continue
        b = buckets[bid]
        keep = default_keep([{"key": o.key, "age_days": o.age_days, "obj": o} for o in objs])["obj"]
        removable = [o for o in objs if o is not keep]
        scan_like = BucketScan(b.name, b.region, b.versioning, [], [])
        out.append({
            "bucket_id": bid, "bucket": b.name, "group": gid, "versioned": b.versioning == "Enabled",
            "recommended_keep_id": keep.id,
            "removable_bytes": sum(o.size_bytes for o in removable),
            "monthly_saving_usd": round(sum(engine.removal_saving(scan_like, o.size_bytes, o.storage_class) for o in removable), 4),
            "objects": [{"id": o.id, "key": o.key, "size_bytes": o.size_bytes, "storage_class": o.storage_class,
                         "last_modified": o.last_modified} for o in sorted(objs, key=lambda o: o.key)],
        })
    out.sort(key=lambda g: g["removable_bytes"], reverse=True)
    return out


def compression_candidates(db: Session, user: User, bucket_id: int | None = None) -> list[dict]:
    q = db.query(S3Object).filter(S3Object.user_id == user.id, S3Object.compress_saving_bytes > 0,
                                  S3Object.is_trashed.is_(False))
    if bucket_id:
        q = q.filter(S3Object.bucket_id == bucket_id)
    names = {b.id: b.name for b in db.query(S3Bucket).filter(S3Bucket.user_id == user.id)}
    return [{"id": o.id, "bucket": names.get(o.bucket_id, ""), "key": o.key, "size_bytes": o.size_bytes,
             "storage_class": o.storage_class, "estimated_saving_bytes": o.compress_saving_bytes}
            for o in q.order_by(S3Object.compress_saving_bytes.desc()).limit(200)]


def preview_recommendation(db: Session, user: User, rec_id: int) -> dict:
    rec = _pending_rec(db, user, rec_id)
    bucket = _bucket(db, user, rec.bucket_id)
    merged, replaced = merge_rule(bucket.lifecycle_rules or [], rec.payload["rule"])
    return {"bucket": bucket.name, "rule": rec.payload["rule"], "existing_rules": bucket.lifecycle_rules or [],
            "resulting_configuration": {"Rules": merged}, "replaces_existing_rule": replaced is not None}


def _pending_rec(db: Session, user: User, rec_id: int) -> S3Recommendation:
    rec = db.query(S3Recommendation).filter(S3Recommendation.id == rec_id, S3Recommendation.user_id == user.id).first()
    if rec is None:
        raise S3Error("Recommendation not found. Run a new scan.")
    if rec.action != "apply_lifecycle":
        raise S3Error("This recommendation is applied object by object, from its own list.")
    if rec.status != "pending":
        raise S3Error("This recommendation was already applied.")
    return rec


# ----------------------------------------------------------------- actions

def _record(db, user, bucket, action, target, detail, undo=None, bytes_affected=0, monthly=0.0, status="success"):
    row = S3Action(user_id=user.id, bucket=bucket, action=action, target=target, detail=detail, undo=undo or {},
                   bytes_affected=bytes_affected, monthly_saving_usd=round(monthly, 4), status=status)
    db.add(row)
    db.commit()
    return row


def apply_recommendation(db: Session, user: User, rec_id: int) -> dict:
    conn = _require_connection(db, user)
    rec = _pending_rec(db, user, rec_id)
    bucket = _bucket(db, user, rec.bucket_id)
    client = _clients(conn)(bucket.region)
    rule = rec.payload["rule"]
    current = lifecycle_rules(client, bucket.name)  # live, not the scan snapshot
    merged, replaced = merge_rule(current, rule)
    put_lifecycle_rules(client, bucket.name, merged)
    bucket.lifecycle_rules = merged
    rec.status = "applied"
    note = (" In Demo Mode it takes effect on the next scan." if conn.is_demo else
            " S3 applies lifecycle rules in a daily background pass, so changes show up within a day or two.")
    _record(db, user, bucket.name, "lifecycle_rule_added", rule["ID"], rec.title + "." + note,
            undo={"type": "lifecycle", "region": bucket.region, "rule_id": rule["ID"], "replaced": replaced},
            monthly=rec.monthly_saving_usd)
    return {"success": True, "message": f"Lifecycle rule {rule['ID']} added to {bucket.name}.{note}",
            "rules": merged}


def _ensure_trash_rule(db, user, client, bucket: S3Bucket) -> None:
    current = lifecycle_rules(client, bucket.name)
    if any(r.get("ID") == TRASH_RULE_ID for r in current):
        return
    rule = {"ID": TRASH_RULE_ID, "Status": "Enabled", "Filter": {"Prefix": TRASH_PREFIX},
            "Expiration": {"Days": TRASH_DAYS}}
    merged, _ = merge_rule(current, rule)
    put_lifecycle_rules(client, bucket.name, merged)
    bucket.lifecycle_rules = merged
    _record(db, user, bucket.name, "lifecycle_rule_added", TRASH_RULE_ID,
            f"Objects CloudClean moves to {TRASH_PREFIX} are deleted by S3 after {TRASH_DAYS} days, like Drive's Trash.",
            undo={"type": "lifecycle", "region": bucket.region, "rule_id": TRASH_RULE_ID, "replaced": None})


def _trash_key(key: str) -> str:
    return f"{TRASH_PREFIX}{datetime.now(timezone.utc):%Y%m%dT%H%M%S}/{key}"


def _move_to_trash(client, bucket: S3Bucket, obj: S3Object) -> dict:
    """Returns the undo record. Versioned: delete marker. Otherwise:
    copy to the trash prefix, verify the copy, then delete the original."""
    if bucket.versioning == "Enabled":
        resp = client.delete_object(Bucket=bucket.name, Key=obj.key)
        return {"type": "delete_marker", "region": bucket.region, "key": obj.key,
                "marker_version_id": resp.get("VersionId")}
    trash_key = _trash_key(obj.key)
    client.copy({"Bucket": bucket.name, "Key": obj.key}, bucket.name, trash_key,
                ExtraArgs={"StorageClass": obj.storage_class})
    if client.head_object(Bucket=bucket.name, Key=trash_key)["ContentLength"] != obj.size_bytes:
        raise S3Error(f"Copy of {obj.key} to {TRASH_PREFIX} could not be verified; the original was left in place.")
    client.delete_object(Bucket=bucket.name, Key=obj.key)
    return {"type": "trash_copy", "region": bucket.region, "key": obj.key, "trash_key": trash_key,
            "storage_class": obj.storage_class}


def trash_duplicates(db: Session, user: User, bucket_id: int, group: int, keep_object_id: int) -> list[dict]:
    conn = _require_connection(db, user)
    bucket = _bucket(db, user, bucket_id)
    objs = db.query(S3Object).filter(S3Object.user_id == user.id, S3Object.bucket_id == bucket_id,
                                     S3Object.duplicate_group == group, S3Object.is_trashed.is_(False)).all()
    if keep_object_id not in {o.id for o in objs}:
        raise S3Error("The object to keep isn't part of this duplicate group.")
    client = _clients(conn)(bucket.region)
    if bucket.versioning != "Enabled":
        _ensure_trash_rule(db, user, client, bucket)
    engine = S3Engine()
    scan_like = BucketScan(bucket.name, bucket.region, bucket.versioning, [], [])
    results = []
    for o in objs:
        if o.id == keep_object_id:
            continue
        try:
            undo = _move_to_trash(client, bucket, o)
        except (*AWS_ERRORS, S3Error) as exc:
            logger.warning("Removing duplicate %s/%s failed: %s", bucket.name, o.key, exc)
            _record(db, user, bucket.name, "trashed", o.key, f"Could not remove: {_msg(exc)}", status="failed")
            results.append({"id": o.id, "key": o.key, "success": False, "message": _msg(exc)})
            continue
        o.is_trashed = True
        monthly = engine.removal_saving(scan_like, o.size_bytes, o.storage_class)
        where = ("delete marker added; the data is kept as a noncurrent version" if undo["type"] == "delete_marker"
                 else f"moved to {undo['trash_key']} (S3 deletes it after {TRASH_DAYS} days)")
        _record(db, user, bucket.name, "trashed", o.key, f"Duplicate removed — {where}.", undo=undo,
                bytes_affected=o.size_bytes, monthly=monthly)
        results.append({"id": o.id, "key": o.key, "success": True, "saved_bytes": o.size_bytes})
    return results


def _compress_bytes(data: bytes, key: str, jpeg_quality: int) -> bytes:
    from app.compression.images import compress_jpeg, compress_png, compress_webp
    from app.compression.pdf import compress_pdf

    ext = key.rsplit(".", 1)[-1].lower()
    if ext in ("jpg", "jpeg"):
        return compress_jpeg(data, quality=jpeg_quality)
    if ext == "png":
        return compress_png(data)
    if ext == "webp":
        return compress_webp(data)
    if ext == "pdf":
        return compress_pdf(data)
    raise S3Error("Only JPEG, PNG, WebP and PDF objects can be compressed.")


def compress_object(db: Session, user: User, object_id: int) -> dict:
    conn = _require_connection(db, user)
    obj = db.query(S3Object).filter(S3Object.id == object_id, S3Object.user_id == user.id,
                                    S3Object.is_trashed.is_(False)).first()
    if obj is None:
        raise S3Error("Object not found. Run a new scan.")
    bucket = _bucket(db, user, obj.bucket_id)
    if obj.size_bytes > MAX_COMPRESS_BYTES:
        raise S3Error("Object is too large for in-app compression in this deployment.")
    client = _clients(conn)(bucket.region)
    head = client.head_object(Bucket=bucket.name, Key=obj.key)
    cls = head.get("StorageClass") or "STANDARD"
    if cls in ("GLACIER", "DEEP_ARCHIVE"):
        raise S3Error("Archived objects must be restored before they can be compressed.")
    original_size = obj.size_bytes
    min_ratio = user.settings.min_saving_percent / 100

    if conn.is_demo:
        jitter = (int(hashlib.sha1(obj.key.encode()).hexdigest(), 16) % 21 - 10) / 100
        new_size = max(1, original_size - int((obj.compress_saving_bytes or original_size * 0.2) * (1 + jitter)))
        new_bytes = None
    else:
        data = client.get_object(Bucket=bucket.name, Key=obj.key)["Body"].read()
        try:
            new_bytes = _compress_bytes(data, obj.key, user.settings.jpeg_quality)
        except UnsafeToCompress as exc:
            obj.compress_saving_bytes = 0  # committed by _record
            _record(db, user, bucket.name, "compressed", obj.key, str(exc), status="skipped")
            return {"success": False, "message": str(exc), "saved_bytes": 0}
        new_size = len(new_bytes)
    saved = original_size - new_size
    if original_size == 0 or saved <= 0 or saved / original_size < min_ratio:
        _record(db, user, bucket.name, "compressed", obj.key, "No meaningful saving; object left unchanged.",
                status="skipped")
        return {"success": False, "message": "No meaningful optimization available.", "saved_bytes": 0}

    # Keep the original restorable before overwriting it.
    if bucket.versioning == "Enabled":
        undo = {"type": "version", "region": bucket.region, "key": obj.key, "version_id": head.get("VersionId"),
                "original_size": original_size, "storage_class": cls}
    else:
        _ensure_trash_rule(db, user, client, bucket)
        trash_key = _trash_key(obj.key)
        client.copy({"Bucket": bucket.name, "Key": obj.key}, bucket.name, trash_key, ExtraArgs={"StorageClass": cls})
        undo = {"type": "backup", "region": bucket.region, "key": obj.key, "trash_key": trash_key,
                "original_size": original_size, "storage_class": cls}

    if conn.is_demo:
        client.simulate_rewrite(bucket.name, obj.key, new_size, cls)
    else:
        extra = {k: head[k] for k in ("ContentType", "CacheControl", "ContentDisposition", "ContentLanguage") if head.get(k)}
        client.put_object(Bucket=bucket.name, Key=obj.key, Body=io.BytesIO(new_bytes), StorageClass=cls,
                          Metadata=head.get("Metadata", {}), **extra)

    obj.size_bytes = new_size
    obj.compress_saving_bytes = 0
    scan_like = BucketScan(bucket.name, bucket.region, bucket.versioning, [], [])
    monthly = S3Engine().removal_saving(scan_like, saved, cls)
    kept = ("the original is kept as a noncurrent version" if undo["type"] == "version"
            else f"the original is kept at {undo['trash_key']} for {TRASH_DAYS} days")
    _record(db, user, bucket.name, "compressed", obj.key,
            f"Re-encoded in place ({_mb(original_size)} → {_mb(new_size)}); {kept}"
            + (" (Demo Mode simulation)." if conn.is_demo else "."),
            undo=undo, bytes_affected=saved, monthly=monthly)
    return {"success": True, "message": f"Saved {_mb(saved)}.", "saved_bytes": saved,
            "original_size_bytes": original_size, "new_size_bytes": new_size}


def undo_action(db: Session, user: User, action_id: int) -> dict:
    conn = _require_connection(db, user)
    action = db.query(S3Action).filter(S3Action.id == action_id, S3Action.user_id == user.id).first()
    if action is None or not action.restorable:
        raise S3Error("This action can't be undone.")
    u = action.undo
    client = _clients(conn)(u.get("region"))
    b = action.bucket
    if u["type"] == "lifecycle":
        current = lifecycle_rules(client, b)
        restored = [r for r in current if r.get("ID") != u["rule_id"]] + ([u["replaced"]] if u.get("replaced") else [])
        put_lifecycle_rules(client, b, restored)
        bucket_row = db.query(S3Bucket).filter(S3Bucket.user_id == user.id, S3Bucket.name == b).first()
        if bucket_row:
            bucket_row.lifecycle_rules = restored
        message = (f"Lifecycle rule {u['rule_id']} removed from {b}. Objects it already moved stay in their "
                   f"new storage class — removing a rule only stops future transitions.")
    elif u["type"] == "delete_marker":
        client.delete_object(Bucket=b, Key=u["key"], VersionId=u["marker_version_id"])
        message = f"{u['key']} restored (delete marker removed)."
    elif u["type"] in ("trash_copy", "backup"):
        client.copy({"Bucket": b, "Key": u["trash_key"]}, b, u["key"], ExtraArgs={"StorageClass": u["storage_class"]})
        client.delete_object(Bucket=b, Key=u["trash_key"])
        message = f"{u['key']} restored from {TRASH_PREFIX}."
    elif u["type"] == "version":
        client.copy({"Bucket": b, "Key": u["key"], "VersionId": u["version_id"]}, b, u["key"],
                    ExtraArgs={"StorageClass": u["storage_class"]})
        message = f"Original version of {u['key']} restored."
    else:
        raise S3Error("Unknown action type.")

    if "key" in u:
        obj = (db.query(S3Object).join(S3Bucket, S3Object.bucket_id == S3Bucket.id)
               .filter(S3Object.user_id == user.id, S3Bucket.name == b, S3Object.key == u["key"]).first())
        if obj:
            obj.is_trashed = False
            if u.get("original_size"):
                obj.size_bytes = u["original_size"]
    action.status = "reverted"
    _record(db, user, b, "undone", action.target, message)
    return {"success": True, "message": message}


def history(db: Session, user: User, limit: int = 200) -> list[dict]:
    rows = (db.query(S3Action).filter(S3Action.user_id == user.id)
            .order_by(S3Action.created_at.desc(), S3Action.id.desc()).limit(limit).all())
    return [{"id": a.id, "bucket": a.bucket, "action": a.action, "target": a.target, "detail": a.detail,
             "bytes_affected": a.bytes_affected, "monthly_saving_usd": a.monthly_saving_usd, "status": a.status,
             "restorable": a.restorable, "created_at": a.created_at} for a in rows]


def _msg(exc: Exception) -> str:
    return describe_error(exc) if isinstance(exc, AWS_ERRORS) else str(exc)


def _mb(size: int) -> str:
    return f"{size / 1024 ** 2:.1f} MB"


__all__ = [
    "S3AccessError", "S3Error", "AWS_ERRORS", "apply_recommendation", "compress_object", "compression_candidates",
    "connect", "connect_demo", "describe_error", "disconnect", "duplicate_groups", "get_connection", "history",
    "overview", "preview_recommendation", "scan", "trash_duplicates", "undo_action", "Pricing",
]

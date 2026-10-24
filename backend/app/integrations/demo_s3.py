"""Demo Mode for S3: a simulated AWS account.

`FakeS3` answers the same boto3 S3 calls CloudClean makes (same argument
names, same response shapes, same ClientError codes), so Demo Mode runs
through exactly the code paths a real account does. Its whole state is a
JSON document kept on the user's S3Connection row.

One deliberate difference: real S3 applies lifecycle rules in a background
pass roughly once a day; here they take effect on the next listing, so a
demo shows the result of a rule right after the next scan.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

MB = 1024 * 1024
GB = 1024 * MB
MIN_TRANSITION_BYTES = 128 * 1024

# Cheapest last: lifecycle only ever moves objects down this list.
_CLASS_ORDER = ["STANDARD", "REDUCED_REDUNDANCY", "INTELLIGENT_TIERING", "STANDARD_IA", "ONEZONE_IA",
                "GLACIER_IR", "GLACIER", "DEEP_ARCHIVE"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _error(code: str, message: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, op)


def _rule_prefix(rule: dict) -> str | None:
    if "Filter" in rule:
        f = rule["Filter"] or {}
        if "Prefix" in f:
            return f["Prefix"]
        if "And" in f:
            return f["And"].get("Prefix", "")
        return "" if not f else None
    return rule.get("Prefix", "")


class FakeS3:
    def __init__(self, state: dict, on_change=None):
        self.state = state
        self._on_change = on_change or (lambda: None)

    # ----------------------------------------------------------- helpers
    def _bucket(self, name: str, op: str) -> dict:
        b = self.state["buckets"].get(name)
        if b is None:
            raise _error("NoSuchBucket", "The specified bucket does not exist", op)
        return b

    def _changed(self):
        self._on_change()

    def _new_version_id(self) -> str:
        self.state["seq"] = self.state.get("seq", 0) + 1
        return hashlib.sha1(f"v{self.state['seq']}".encode()).hexdigest()[:20]

    def _apply_lifecycle(self, b: dict):
        """What S3's daily lifecycle pass would have done by now."""
        rules = [r for r in (b.get("lifecycle") or []) if r.get("Status") == "Enabled"]
        if not rules:
            return
        now = _now()
        changed = False
        for rule in rules:
            prefix = _rule_prefix(rule)
            if prefix is None:
                continue
            for key, versions in list(b["objects"].items()):
                if not key.startswith(prefix):
                    continue
                for i, v in enumerate(versions):
                    if v.get("delete_marker"):
                        continue
                    if i == 0:  # current version
                        age = (now - _dt(v["last_modified"])).days
                        exp = rule.get("Expiration", {}).get("Days")
                        if exp is not None and age >= exp:
                            if b["versioning"] == "Enabled":
                                versions.insert(0, {"version_id": self._new_version_id(), "delete_marker": True,
                                                    "last_modified": _iso(now)})
                            else:
                                del b["objects"][key]
                            changed = True
                            break
                        changed |= self._transition(v, age, rule.get("Transitions", []), "Days")
                    else:  # noncurrent since the next-newer version was written
                        nc_days = (now - _dt(versions[i - 1]["last_modified"])).days
                        changed |= self._transition(v, nc_days, rule.get("NoncurrentVersionTransitions", []), "NoncurrentDays")
            abort = rule.get("AbortIncompleteMultipartUpload", {}).get("DaysAfterInitiation")
            if abort is not None:
                keep = [u for u in b["uploads"] if not (u["key"].startswith(prefix) and (now - _dt(u["initiated"])).days >= abort)]
                if len(keep) != len(b["uploads"]):
                    b["uploads"] = keep
                    changed = True
        if changed:
            self._changed()

    @staticmethod
    def _transition(v: dict, age: int, transitions: list[dict], day_field: str) -> bool:
        due = [t for t in transitions if age >= t.get(day_field, 0)]
        if not due or v["size"] < MIN_TRANSITION_BYTES:
            return False
        target = max(due, key=lambda t: t.get(day_field, 0))["StorageClass"]
        current = v.get("storage_class", "STANDARD")
        if _CLASS_ORDER.index(target) <= _CLASS_ORDER.index(current):
            return False
        v["storage_class"] = target
        return True

    # ----------------------------------------------------------- buckets
    def list_buckets(self):
        return {"Buckets": [{"Name": n, "CreationDate": _dt(b["created"])} for n, b in sorted(self.state["buckets"].items())]}

    def get_bucket_location(self, Bucket):
        region = self._bucket(Bucket, "GetBucketLocation")["region"]
        return {"LocationConstraint": None if region == "us-east-1" else region}

    def get_bucket_versioning(self, Bucket):
        status = self._bucket(Bucket, "GetBucketVersioning")["versioning"]
        return {"Status": status} if status else {}

    def get_bucket_lifecycle_configuration(self, Bucket):
        rules = self._bucket(Bucket, "GetBucketLifecycleConfiguration").get("lifecycle")
        if not rules:
            raise _error("NoSuchLifecycleConfiguration", "The lifecycle configuration does not exist",
                         "GetBucketLifecycleConfiguration")
        return {"Rules": [dict(r) for r in rules]}

    def put_bucket_lifecycle_configuration(self, Bucket, LifecycleConfiguration):
        b = self._bucket(Bucket, "PutBucketLifecycleConfiguration")
        rules = LifecycleConfiguration.get("Rules", [])
        ids = [r.get("ID") for r in rules]
        if len(ids) != len(set(ids)):
            raise _error("InvalidArgument", "Rule ID must be unique", "PutBucketLifecycleConfiguration")
        b["lifecycle"] = [dict(r) for r in rules]
        self._changed()
        return {}

    def delete_bucket_lifecycle(self, Bucket):
        self._bucket(Bucket, "DeleteBucketLifecycle")["lifecycle"] = []
        self._changed()
        return {}

    # ----------------------------------------------------------- listings
    def list_objects_v2(self, Bucket, MaxKeys=1000, ContinuationToken=None, **_):
        b = self._bucket(Bucket, "ListObjectsV2")
        self._apply_lifecycle(b)
        contents = [
            {"Key": key, "Size": v[0]["size"], "StorageClass": v[0].get("storage_class", "STANDARD"),
             "LastModified": _dt(v[0]["last_modified"]), "ETag": v[0]["etag"]}
            for key, v in sorted(b["objects"].items()) if v and not v[0].get("delete_marker")
        ]
        return {"Contents": contents, "IsTruncated": False, "KeyCount": len(contents)}

    def list_object_versions(self, Bucket, MaxKeys=1000, **_):
        b = self._bucket(Bucket, "ListObjectVersions")
        self._apply_lifecycle(b)
        versions, markers = [], []
        for key, vs in sorted(b["objects"].items()):
            for i, v in enumerate(vs):
                common = {"Key": key, "VersionId": v["version_id"], "IsLatest": i == 0,
                          "LastModified": _dt(v["last_modified"])}
                if v.get("delete_marker"):
                    markers.append(common)
                else:
                    versions.append({**common, "Size": v["size"], "ETag": v["etag"],
                                     "StorageClass": v.get("storage_class", "STANDARD")})
        return {"Versions": versions, "DeleteMarkers": markers, "IsTruncated": False}

    def list_multipart_uploads(self, Bucket, **_):
        b = self._bucket(Bucket, "ListMultipartUploads")
        self._apply_lifecycle(b)
        return {"Uploads": [{"Key": u["key"], "UploadId": u["upload_id"], "Initiated": _dt(u["initiated"]),
                             "StorageClass": "STANDARD"} for u in b["uploads"]], "IsTruncated": False}

    def list_parts(self, Bucket, Key, UploadId, **_):
        b = self._bucket(Bucket, "ListParts")
        up = next((u for u in b["uploads"] if u["upload_id"] == UploadId), None)
        if up is None:
            raise _error("NoSuchUpload", "The specified upload does not exist", "ListParts")
        part = 100 * MB
        sizes = [part] * (up["size"] // part) + ([up["size"] % part] if up["size"] % part else [])
        return {"Parts": [{"PartNumber": i + 1, "Size": s} for i, s in enumerate(sizes)], "IsTruncated": False}

    # ----------------------------------------------------------- objects
    def _current(self, b: dict, key: str, op: str, version_id: str | None = None) -> dict:
        vs = b["objects"].get(key) or []
        if version_id:
            v = next((v for v in vs if v["version_id"] == version_id), None)
        else:
            v = vs[0] if vs and not vs[0].get("delete_marker") else None
        if v is None or v.get("delete_marker"):
            raise _error("NoSuchKey", "The specified key does not exist.", op)
        return v

    def head_object(self, Bucket, Key, VersionId=None):
        v = self._current(self._bucket(Bucket, "HeadObject"), Key, "HeadObject", VersionId)
        return {"ContentLength": v["size"], "ETag": v["etag"], "StorageClass": v.get("storage_class", "STANDARD"),
                "VersionId": v["version_id"], "LastModified": _dt(v["last_modified"])}

    def _write(self, b: dict, key: str, entry: dict) -> str | None:
        entry["version_id"] = self._new_version_id() if b["versioning"] == "Enabled" else "null"
        if b["versioning"] == "Enabled":
            b["objects"].setdefault(key, []).insert(0, entry)
        else:
            b["objects"][key] = [entry]
        return entry["version_id"] if b["versioning"] == "Enabled" else None

    def copy_object(self, Bucket, Key, CopySource, StorageClass=None, MetadataDirective="COPY", **_):
        src_bucket = self._bucket(CopySource["Bucket"], "CopyObject")
        src = self._current(src_bucket, CopySource["Key"], "CopyObject", CopySource.get("VersionId"))
        if src.get("storage_class") in ("GLACIER", "DEEP_ARCHIVE"):
            raise _error("InvalidObjectState", "The operation is not valid for the object's storage class", "CopyObject")
        dest = self._bucket(Bucket, "CopyObject")
        version = self._write(dest, Key, {"size": src["size"], "etag": src["etag"],
                                          "storage_class": StorageClass or "STANDARD", "last_modified": _iso(_now())})
        self._changed()
        return {"VersionId": version} if version else {}

    def copy(self, CopySource, Bucket, Key, ExtraArgs=None, **_):
        """boto3's managed copy (multipart for > 5 GB); same effect here."""
        self.copy_object(Bucket=Bucket, Key=Key, CopySource=CopySource, **(ExtraArgs or {}))

    def delete_object(self, Bucket, Key, VersionId=None):
        b = self._bucket(Bucket, "DeleteObject")
        vs = b["objects"].get(Key)
        if VersionId:
            if vs:
                b["objects"][Key] = [v for v in vs if v["version_id"] != VersionId]
                if not b["objects"][Key]:
                    del b["objects"][Key]
            self._changed()
            return {"VersionId": VersionId}
        if b["versioning"] == "Enabled":
            marker = {"version_id": self._new_version_id(), "delete_marker": True, "last_modified": _iso(_now())}
            b["objects"].setdefault(Key, []).insert(0, marker)
            self._changed()
            return {"DeleteMarker": True, "VersionId": marker["version_id"]}
        b["objects"].pop(Key, None)
        self._changed()
        return {}

    # Demo-only: objects here are size records, not bytes, so compression is simulated.
    def simulate_rewrite(self, Bucket, Key, new_size: int, storage_class: str) -> str | None:
        b = self._bucket(Bucket, "PutObject")
        etag = '"' + hashlib.md5(f"{Key}:{new_size}".encode()).hexdigest() + '"'
        version = self._write(b, Key, {"size": new_size, "etag": etag, "storage_class": storage_class,
                                       "last_modified": _iso(_now())})
        self._changed()
        return version


# ------------------------------------------------------------- demo account

def generate_demo_state(seed: int = 11) -> dict:
    """A small company's S3 account with the classic sources of waste:
    never-tiered old data, duplicate uploads, abandoned multipart uploads,
    piles of noncurrent versions, and uncompressed images/PDFs."""
    rng = random.Random(seed)
    now = _now()
    state: dict = {"seq": 0, "buckets": {}}

    def bucket(name, region, versioning="", lifecycle=None):
        state["buckets"][name] = {"region": region, "versioning": versioning, "lifecycle": lifecycle or [],
                                  "created": _iso(now - timedelta(days=800)), "objects": {}, "uploads": []}
        return state["buckets"][name]

    def put(b, key, size, age_days, storage_class="STANDARD", content=None):
        state["seq"] += 1
        etag = '"' + hashlib.md5(f"{content or key}:{size}".encode()).hexdigest() + '"'
        vid = hashlib.sha1(f"v{state['seq']}".encode()).hexdigest()[:20] if b["versioning"] == "Enabled" else "null"
        entry = {"version_id": vid, "size": size, "etag": etag, "storage_class": storage_class,
                 "last_modified": _iso(now - timedelta(days=age_days, hours=rng.randint(0, 23)))}
        b["objects"].setdefault(key, []).append(entry)  # appended = older than what's already there

    # 1. Media assets: images and PDFs (compressible), duplicate uploads, small thumbnails, videos
    media = bucket("acme-media-assets", "us-east-1")
    for i in range(90):
        ext = rng.choice([".jpg", ".jpg", ".jpg", ".png"])
        size = rng.randint(2 * MB, 14 * MB)
        age = rng.randint(5, 900)
        put(media, f"images/product_{i:03d}{ext}", size, age)
        if i % 9 == 0:  # same file uploaded again under another key
            put(media, f"images/uploads/product_{i:03d}_copy{ext}", size, max(1, age - rng.randint(1, 40)),
                content=f"images/product_{i:03d}{ext}")
    for i in range(160):
        put(media, f"thumbnails/t_{i:03d}.webp", rng.randint(8 * 1024, 90 * 1024), rng.randint(5, 900))
    for i in range(35):
        put(media, f"docs/brochure_{i:02d}.pdf", rng.randint(3 * MB, 60 * MB), rng.randint(20, 800))
    for i in range(14):
        put(media, f"videos/launch_{i:02d}.mp4", rng.randint(300 * MB, 2 * GB), rng.randint(40, 700))

    # 2. Application logs: never tiered, plus abandoned multipart uploads
    logs = bucket("acme-app-logs", "ap-south-1")
    for day in range(0, 720, 4):
        put(logs, f"logs/{(now - timedelta(days=day)):%Y/%m/%d}/app.log", rng.randint(40 * MB, 220 * MB), day)
    for i in range(4):
        logs["uploads"].append({"key": f"exports/full_export_{i}.tar", "upload_id": f"demo-upload-{i}",
                                "initiated": _iso(now - timedelta(days=rng.randint(15, 300))),
                                "size": rng.randint(800 * MB, 6 * GB)})

    # 3. Database backups: versioned; "latest" is overwritten daily, so old copies pile up as noncurrent versions
    backups = bucket("acme-db-backups", "us-east-1", versioning="Enabled")
    for week in range(1, 100):
        put(backups, f"backups/weekly/db-{(now - timedelta(weeks=week)):%Y-%m-%d}.sql.gz",
            rng.randint(1 * GB, 3 * GB), week * 7)
    for day in range(0, 75):  # newest first: index 0 is the current version
        put(backups, "backups/latest.sql.gz", rng.randint(int(1.8 * GB), int(2.4 * GB)), day)

    # 4. Static website: tiny files, already has a hygiene rule — little to do here
    site = bucket("acme-static-site", "us-east-1", lifecycle=[{
        "ID": "abort-stale-uploads", "Status": "Enabled", "Filter": {"Prefix": ""},
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
    }])
    for i in range(70):
        put(site, f"assets/{rng.choice(['app', 'vendor', 'style'])}_{i:02d}.{rng.choice(['js', 'css', 'svg'])}",
            rng.randint(2 * 1024, 110 * 1024), rng.randint(1, 400))
    put(site, "index.html", 18 * 1024, 3)
    return state

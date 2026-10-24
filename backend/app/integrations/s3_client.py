"""AWS S3 access. Everything CloudClean needs is a handful of boto3 S3 calls;
this module creates the right client (a real boto3 client, or the simulated
one in Demo Mode — both expose the same methods) and pages through
listings with hard caps so a huge bucket can't run away with time or
request costs.

Scan cost: one LIST request per 1,000 objects/versions/uploads. A bucket of
50,000 objects costs ~50 LIST requests (about $0.00025); the AWS free tier
includes 2,000 a month on accounts that have the classic free tier.
"""
from __future__ import annotations

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.integrations.demo_s3 import FakeS3

MAX_OBJECTS_PER_BUCKET = 50_000
MAX_VERSIONS_PER_BUCKET = 100_000
MAX_UPLOADS_PER_BUCKET = 200

_BOTO_CONFIG = Config(retries={"max_attempts": 5, "mode": "standard"}, connect_timeout=10, read_timeout=60)


class S3AccessError(Exception):
    """Credentials rejected, permission missing, or AWS unreachable — shown to the user as-is."""


def describe_error(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        err = exc.response.get("Error", {})
        code = err.get("Code", "Error")
        hints = {
            "AccessDenied": "the IAM policy for these keys is missing a permission",
            "InvalidAccessKeyId": "the access key ID doesn't exist",
            "SignatureDoesNotMatch": "the secret access key is wrong",
            "ExpiredToken": "the credentials have expired",
        }
        hint = hints.get(code)
        return f"AWS {code}: {err.get('Message', '')}".strip() + (f" ({hint})" if hint else "")
    return f"Could not reach AWS: {exc}"


def validate_credentials(access_key_id: str, secret_access_key: str, region: str) -> dict:
    """Returns {"account_id", "arn"} or raises S3AccessError."""
    try:
        sts = boto3.client("sts", aws_access_key_id=access_key_id, aws_secret_access_key=secret_access_key,
                           region_name=region, config=_BOTO_CONFIG)
        ident = sts.get_caller_identity()
    except (ClientError, BotoCoreError) as exc:
        raise S3AccessError(describe_error(exc)) from exc
    return {"account_id": ident["Account"], "arn": ident["Arn"]}


class ClientFactory:
    """Per-region clients for one connection (each bucket lives in a region)."""

    def __init__(self, conn, on_demo_change=None):
        """on_demo_change(state) is called after every simulated write so the
        caller can persist the demo account's state."""
        self._conn = conn
        self._clients: dict[str, object] = {}
        self._fake = None
        if conn.is_demo:
            self._fake = FakeS3(conn.demo_state, on_change=lambda: on_demo_change and on_demo_change(self._fake.state))

    def __call__(self, region: str | None = None):
        if self._fake is not None:
            return self._fake
        region = region or self._conn.region or "us-east-1"
        if region not in self._clients:
            self._clients[region] = boto3.client(
                "s3", aws_access_key_id=self._conn.access_key_id,
                aws_secret_access_key=self._conn.secret_access_key, region_name=region, config=_BOTO_CONFIG,
            )
        return self._clients[region]


def bucket_region(client, bucket: str) -> str:
    # us-east-1 is reported as None (and legacy EU as "EU").
    loc = client.get_bucket_location(Bucket=bucket).get("LocationConstraint")
    return {None: "us-east-1", "": "us-east-1", "EU": "eu-west-1"}.get(loc, loc)


def lifecycle_rules(client, bucket: str) -> list[dict]:
    try:
        return client.get_bucket_lifecycle_configuration(Bucket=bucket).get("Rules", [])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NoSuchLifecycleConfiguration":
            return []
        raise


def put_lifecycle_rules(client, bucket: str, rules: list[dict]) -> None:
    if rules:
        client.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration={"Rules": rules})
    else:
        client.delete_bucket_lifecycle(Bucket=bucket)


def versioning_status(client, bucket: str) -> str:
    return client.get_bucket_versioning(Bucket=bucket).get("Status", "")


def list_current_objects(client, bucket: str, limit: int = MAX_OBJECTS_PER_BUCKET) -> tuple[list[dict], bool]:
    """(objects, truncated) for an unversioned bucket."""
    out: list[dict] = []
    token = None
    while True:
        kwargs = {"Bucket": bucket, "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        out.extend(resp.get("Contents", []))
        if len(out) >= limit:
            return out[:limit], True
        if not resp.get("IsTruncated"):
            return out, False
        token = resp["NextContinuationToken"]


def list_all_versions(client, bucket: str, limit: int = MAX_VERSIONS_PER_BUCKET) -> tuple[list[dict], list[dict], bool]:
    """(versions, delete_markers, truncated) for a versioned bucket. S3 returns
    each key's versions newest first, which callers rely on."""
    versions: list[dict] = []
    markers: list[dict] = []
    key_marker = version_marker = None
    while True:
        kwargs = {"Bucket": bucket, "MaxKeys": 1000}
        if key_marker:
            kwargs["KeyMarker"] = key_marker
            if version_marker:
                kwargs["VersionIdMarker"] = version_marker
        resp = client.list_object_versions(**kwargs)
        versions.extend(resp.get("Versions", []))
        markers.extend(resp.get("DeleteMarkers", []))
        if len(versions) >= limit:
            return versions[:limit], markers, True
        if not resp.get("IsTruncated"):
            return versions, markers, False
        key_marker, version_marker = resp.get("NextKeyMarker"), resp.get("NextVersionIdMarker")


def list_incomplete_uploads(client, bucket: str, limit: int = MAX_UPLOADS_PER_BUCKET) -> list[dict]:
    """Unfinished multipart uploads with the bytes their parts occupy (billed,
    but invisible in the console's object list)."""
    uploads: list[dict] = []
    key_marker = upload_marker = None
    while len(uploads) < limit:
        kwargs = {"Bucket": bucket}
        if key_marker:
            kwargs.update(KeyMarker=key_marker, UploadIdMarker=upload_marker)
        resp = client.list_multipart_uploads(**kwargs)
        uploads.extend(resp.get("Uploads", []))
        if not resp.get("IsTruncated"):
            break
        key_marker, upload_marker = resp.get("NextKeyMarker"), resp.get("NextUploadIdMarker")
    out = []
    for up in uploads[:limit]:
        size = 0
        part_marker = None
        while True:
            kwargs = {"Bucket": bucket, "Key": up["Key"], "UploadId": up["UploadId"]}
            if part_marker:
                kwargs["PartNumberMarker"] = part_marker
            parts = client.list_parts(**kwargs)
            size += sum(p.get("Size", 0) for p in parts.get("Parts", []))
            if not parts.get("IsTruncated"):
                break
            part_marker = parts.get("NextPartNumberMarker")
        out.append({"key": up["Key"], "upload_id": up["UploadId"], "initiated": up["Initiated"], "size": size,
                    "storage_class": up.get("StorageClass", "STANDARD")})
    return out


__all__ = [
    "ClientError", "BotoCoreError", "ClientFactory", "S3AccessError", "bucket_region", "describe_error",
    "lifecycle_rules", "list_all_versions", "list_current_objects", "list_incomplete_uploads",
    "put_lifecycle_rules", "validate_credentials", "versioning_status",
]

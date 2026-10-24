"""ORM models for the AWS S3 provider. Kept apart from the Drive/Gmail models
because S3's unit of storage (objects in buckets, each with a storage class,
plus versions and multipart uploads) and its savings (tiering, lifecycle
rules) differ from Drive's."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models import now_utc
from app.security.crypto import EncryptedText


class S3Connection(Base):
    """One AWS account per CloudClean user. Keys are encrypted at rest; Demo
    Mode keeps a simulated account's whole state in `demo_state` instead."""

    __tablename__ = "s3_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    access_key_id: Mapped[str] = mapped_column(EncryptedText, default="")
    secret_access_key: Mapped[str] = mapped_column(EncryptedText, default="")
    region: Mapped[str] = mapped_column(String(32), default="us-east-1")
    account_id: Mapped[str] = mapped_column(String(32), default="")
    arn: Mapped[str] = mapped_column(String(300), default="")
    demo_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class S3Bucket(Base):
    __tablename__ = "s3_buckets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    region: Mapped[str] = mapped_column(String(32), default="")
    versioning: Mapped[str] = mapped_column(String(16), default="")  # "" | Enabled | Suspended
    lifecycle_rules: Mapped[list] = mapped_column(JSON, default=list)
    object_count: Mapped[int] = mapped_column(Integer, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    bytes_by_class: Mapped[dict] = mapped_column(JSON, default=dict)
    noncurrent_bytes: Mapped[int] = mapped_column(Integer, default=0)
    noncurrent_count: Mapped[int] = mapped_column(Integer, default=0)
    incomplete_upload_bytes: Mapped[int] = mapped_column(Integer, default=0)
    incomplete_upload_count: Mapped[int] = mapped_column(Integer, default=0)
    small_object_count: Mapped[int] = mapped_column(Integer, default=0)  # < 128 KB: never tiered
    monthly_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)  # listing hit the scan cap
    scan_error: Mapped[str] = mapped_column(Text, default="")
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class S3Object(Base):
    """Current version of one object (noncurrent versions are only aggregated)."""

    __tablename__ = "s3_objects"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    bucket_id: Mapped[int] = mapped_column(ForeignKey("s3_buckets.id"), index=True)
    key: Mapped[str] = mapped_column(String(1024))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_class: Mapped[str] = mapped_column(String(32), default="STANDARD")
    last_modified: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    age_days: Mapped[int] = mapped_column(Integer, default=0)
    etag: Mapped[str] = mapped_column(String(80), default="")
    duplicate_group: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    compress_saving_bytes: Mapped[int] = mapped_column(Integer, default=0)  # estimate, 0 = not a candidate
    is_trashed: Mapped[bool] = mapped_column(Boolean, default=False)


class S3Recommendation(Base):
    __tablename__ = "s3_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    bucket_id: Mapped[int] = mapped_column(ForeignKey("s3_buckets.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))  # abort_uploads | noncurrent | tiering | duplicates | compress
    action: Mapped[str] = mapped_column(String(32))  # apply_lifecycle | review_duplicates | review_compression
    title: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str] = mapped_column(Text)
    saving_bytes: Mapped[int] = mapped_column(Integer, default=0)
    monthly_saving_usd: Mapped[float] = mapped_column(Float, default=0.0)
    one_time_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    risk: Mapped[str] = mapped_column(String(16), default="low")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. the lifecycle rule to add
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | applied
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class S3Action(Base):
    """History of every change CloudClean made in S3, with what's needed to undo it."""

    __tablename__ = "s3_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    bucket: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(32))  # lifecycle_rule_added | trashed | compressed | undone
    target: Mapped[str] = mapped_column(String(1024))  # rule ID or object key
    detail: Mapped[str] = mapped_column(Text, default="")
    undo: Mapped[dict] = mapped_column(JSON, default=dict)  # what restore needs (previous rule, marker/version id, trash key)
    bytes_affected: Mapped[int] = mapped_column(Integer, default=0)
    monthly_saving_usd: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="success")  # success | failed | reverted
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    @property
    def restorable(self) -> bool:
        return self.status == "success" and bool(self.undo)

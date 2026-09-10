"""SQLAlchemy ORM models for CloudClean."""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    picture_url: Mapped[str] = mapped_column(String(500), default="")

    # OAuth tokens — access token is short-lived, refresh token lets us re-auth silently.
    access_token: Mapped[str] = mapped_column(Text, default="")
    refresh_token: Mapped[str] = mapped_column(Text, default="")
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    settings: Mapped["UserSettings"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    files: Mapped[list["DriveFile"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)

    large_file_mb: Mapped[int] = mapped_column(Integer, default=100)
    very_large_file_mb: Mapped[int] = mapped_column(Integer, default=500)
    huge_file_mb: Mapped[int] = mapped_column(Integer, default=1024)
    inactive_days: Mapped[int] = mapped_column(Integer, default=365)
    jpeg_quality: Mapped[int] = mapped_column(Integer, default=75)
    allow_format_conversion: Mapped[bool] = mapped_column(Boolean, default=False)
    min_saving_percent: Mapped[float] = mapped_column(Float, default=10.0)
    region: Mapped[str] = mapped_column(String(8), default="IN")

    user: Mapped["User"] = relationship(back_populates="settings")


class DriveFile(Base):
    __tablename__ = "drive_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    drive_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(1024))
    mime_type: Mapped[str] = mapped_column(String(255), index=True)
    extension: Mapped[str] = mapped_column(String(32), default="")
    category: Mapped[str] = mapped_column(String(32), default="other")  # images/video/audio/pdf/docs/...
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    created_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    modified_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    parent_id: Mapped[str] = mapped_column(String(128), default="")
    web_url: Mapped[str] = mapped_column(String(1000), default="")

    is_google_workspace_file: Mapped[bool] = mapped_column(Boolean, default=False)
    is_trashed: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=True, index=True)  # SHA-256, when computed

    duplicate_group_id: Mapped[int | None] = mapped_column(ForeignKey("duplicate_groups.id"), nullable=True)
    inactivity_days: Mapped[int] = mapped_column(Integer, default=0)

    optimization_score: Mapped[float] = mapped_column(Float, default=0.0)
    recommendation_type: Mapped[str] = mapped_column(String(32), default="keep")
    estimated_savings_bytes: Mapped[int] = mapped_column(Integer, default=0)
    risk_level: Mapped[str] = mapped_column(String(16), default="low")

    user: Mapped["User"] = relationship(back_populates="files")
    duplicate_group: Mapped["DuplicateGroup"] = relationship(back_populates="files")


class DuplicateGroup(Base):
    __tablename__ = "duplicate_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    match_level: Mapped[str] = mapped_column(String(16), default="hash")  # name / size_name / hash
    recommended_keep_drive_id: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    files: Mapped[list["DriveFile"]] = relationship(back_populates="duplicate_group")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("drive_files.id"), nullable=True)
    duplicate_group_id: Mapped[int | None] = mapped_column(ForeignKey("duplicate_groups.id"), nullable=True)

    type: Mapped[str] = mapped_column(String(32))  # compress / archive / duplicate / review / remove
    reason: Mapped[str] = mapped_column(Text)
    estimated_saving_bytes: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    risk: Mapped[str] = mapped_column(String(16), default="low")
    action: Mapped[str] = mapped_column(String(32), default="review")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/ignored/done
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class OptimizationAction(Base):
    __tablename__ = "optimization_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(1024))
    file_drive_id: Mapped[str] = mapped_column(String(128), default="")
    action: Mapped[str] = mapped_column(String(32))  # compressed/archived/trashed/restored/ignored
    original_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    new_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    saved_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="success")  # success/failed/reverted
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    files_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_found: Mapped[int] = mapped_column(Integer, default=0)
    total_recoverable_bytes: Mapped[int] = mapped_column(Integer, default=0)
    optimization_score: Mapped[float] = mapped_column(Float, default=0.0)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StorageSnapshot(Base):
    __tablename__ = "storage_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    used_bytes: Mapped[int] = mapped_column(Integer, default=0)
    quota_bytes: Mapped[int] = mapped_column(Integer, default=0)
    recoverable_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)

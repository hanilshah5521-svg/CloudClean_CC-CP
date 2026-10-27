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
from app.security.crypto import EncryptedText


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    picture_url: Mapped[str] = mapped_column(String(500), default="")

    # OAuth tokens — access token is short-lived, refresh token lets us re-auth
    # silently. Both are encrypted at rest (see app/security/crypto.py).
    access_token: Mapped[str] = mapped_column(EncryptedText, default="")
    refresh_token: Mapped[str] = mapped_column(EncryptedText, default="")
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Space-separated scopes the user actually granted (Google lets them untick Gmail).
    granted_scopes: Mapped[str] = mapped_column(Text, default="")

    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # Several Google accounts of one person share a profile key (empty = on
    # its own). Each account keeps its own token, scans and history; the
    # session's user_id is the account currently being worked in.
    profile_key: Mapped[str] = mapped_column(String(32), default="", index=True)
    # Demo Mode: 0 = the main simulated Drive, 1+ = extra simulated accounts.
    demo_variant: Mapped[int] = mapped_column(Integer, default=0)
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
    gmail_min_mb: Mapped[int] = mapped_column(Integer, default=5)
    # When the worker last evaluated this user's auto-compression rules.
    rules_last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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
    content_hash: Mapped[str] = mapped_column(String(64), nullable=True, index=True)  # Drive's sha256/md5 checksum
    folder_path: Mapped[str] = mapped_column(String(2048), default="")  # e.g. "My Drive / College / DAA"
    # Drive's videoMediaMetadata (0 = not reported) — lets the video bitrate,
    # and so the re-encoding saving, be estimated without a download.
    video_width: Mapped[int] = mapped_column(Integer, default=0)
    video_height: Mapped[int] = mapped_column(Integer, default=0)
    video_duration_ms: Mapped[int] = mapped_column(Integer, default=0)

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

    file: Mapped["DriveFile | None"] = relationship(lazy="joined")

    @property
    def file_name(self) -> str | None:
        return self.file.name if self.file else None

    @property
    def file_drive_id(self) -> str | None:
        return self.file.drive_id if self.file else None

    @property
    def file_web_url(self) -> str | None:
        return self.file.web_url if self.file else None

    @property
    def file_parent_id(self) -> str | None:
        return self.file.parent_id if self.file else None


class OptimizationAction(Base):
    __tablename__ = "optimization_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(1024))
    file_drive_id: Mapped[str] = mapped_column(String(128), default="")
    # compressed / archived / archive_created / trashed / gmail_trashed / restored
    action: Mapped[str] = mapped_column(String(32))
    original_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    new_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    saved_bytes: Mapped[int] = mapped_column(Integer, default=0)
    # success/skipped/failed/reverted, or in_progress while a background job
    # is uploading (so an interrupted upload still leaves a record behind)
    status: Mapped[str] = mapped_column(String(16), default="success")
    detail: Mapped[str] = mapped_column(Text, default="")
    # For "compressed": the Drive revision holding the original bytes, so the
    # compression can be undone while Drive still keeps that revision.
    revision_id: Mapped[str] = mapped_column(String(128), default="")
    # For "compressed": when CloudClean deletes that kept original. Drive marks
    # uploads "Keep forever" (a flag its API can't turn off), so the original
    # keeps using storage until its version is deleted. Cleared once deleted.
    original_delete_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # For "organized": what Undo needs — the folder, whether CloudClean created
    # it, and each moved file's previous folder.
    undo_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    @property
    def restorable(self) -> bool:
        if self.status != "success":
            return False
        if self.action in ("trashed", "archived", "gmail_trashed"):
            return bool(self.file_drive_id)
        if self.action == "organized":
            return bool(self.undo_data)
        return self.action == "compressed" and bool(self.revision_id)

    @property
    def can_free_space(self) -> bool:
        """A compression whose "Keep forever" original is still stored."""
        return (self.action == "compressed" and self.status == "success" and bool(self.revision_id)
                and self.original_delete_at is not None)


class OrganizeSuggestion(Base):
    """Loose files sharing a naming convention, suggested to go into one folder."""

    __tablename__ = "organize_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    parent_id: Mapped[str] = mapped_column(String(128))
    parent_name: Mapped[str] = mapped_column(String(1024), default="")
    folder_name: Mapped[str] = mapped_column(String(255))
    existing_folder_id: Mapped[str] = mapped_column(String(128), default="")
    pattern: Mapped[str] = mapped_column(String(1024), default="")
    category: Mapped[str] = mapped_column(String(32), default="other")
    drive_ids: Mapped[list] = mapped_column(JSON, default=list)
    names: Mapped[list] = mapped_column(JSON, default=list)
    total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | applied | dismissed
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
    # Where the quota goes. Drive, Gmail and Photos share one quota; Google's
    # API reports Drive (and Drive's Trash) separately, the rest is Gmail + Photos.
    drive_bytes: Mapped[int] = mapped_column(Integer, default=0)
    drive_trash_bytes: Mapped[int] = mapped_column(Integer, default=0)
    gmail_photos_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)


class GmailMessage(Base):
    """A large Gmail message (metadata only — bodies are never fetched)."""

    __tablename__ = "gmail_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    message_id: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), default="")
    subject: Mapped[str] = mapped_column(String(1000), default="")
    sender: Mapped[str] = mapped_column(String(500), default="")
    received_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    labels: Mapped[str] = mapped_column(Text, default="")
    has_attachment: Mapped[bool] = mapped_column(Boolean, default=False)
    inactivity_days: Mapped[int] = mapped_column(Integer, default=0)
    is_trashed: Mapped[bool] = mapped_column(Boolean, default=False)


class Job(Base):
    """Background work run by the worker process (`python -m app.worker`):
    analysis, video compression, large restores, rule evaluation."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # analyze / compress_video / compress_file / restore / evaluate_rules
    kind: Mapped[str] = mapped_column(String(32), index=True)
    # What the job works on (a Drive file ID, a History action ID) — used to
    # avoid queueing the same work twice.
    target: Mapped[str] = mapped_column(String(128), default="", index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued/running/done/failed
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    message: Mapped[str] = mapped_column(String(255), default="")  # current step, for the UI
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkerHeartbeat(Base):
    """One row per running worker, refreshed every few seconds, so the UI can
    tell "queued, worker busy" apart from "queued, no worker running"."""

    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)  # host:pid
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class CompressionRule(Base):
    """A rule like "compress videos larger than N MB not modified in M days".
    Evaluated nightly by the worker; matches become RuleSuggestions. Only applied
    without asking when the user turned auto_apply on for this rule."""

    __tablename__ = "compression_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(16), default="video")  # video / images / pdf
    min_size_mb: Mapped[int] = mapped_column(Integer, default=200)
    min_inactive_days: Mapped[int] = mapped_column(Integer, default=90)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_apply: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class RuleSuggestion(Base):
    """A file a rule matched. Keyed by Drive file ID (DriveFile rows are
    rebuilt on every analysis), so it survives re-analysis."""

    __tablename__ = "rule_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("compression_rules.id"), nullable=True)
    drive_id: Mapped[str] = mapped_column(String(128), index=True)
    file_name: Mapped[str] = mapped_column(String(1024), default="")
    category: Mapped[str] = mapped_column(String(16), default="video")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    estimated_saving_bytes: Mapped[int] = mapped_column(Integer, default=0)
    # pending / queued / applied / skipped / failed / dismissed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

"""Pydantic request/response schemas."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
    picture_url: str
    is_demo: bool


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    drive_id: str
    name: str
    mime_type: str
    extension: str
    category: str
    size_bytes: int
    created_time: datetime | None
    modified_time: datetime | None
    web_url: str
    parent_id: str = ""  # Drive folder it's in (links "Show in folder")
    is_google_workspace_file: bool
    content_hash: str | None = None
    folder_path: str = ""
    duplicate_group_id: int | None
    inactivity_days: int
    optimization_score: float
    recommendation_type: str
    estimated_savings_bytes: int
    risk_level: str


class StorageOverview(BaseModel):
    used_bytes: int
    quota_bytes: int
    used_percent: float
    remaining_bytes: int
    recoverable_bytes: int
    projected_used_bytes: int
    projected_used_percent: float


class OptimizationScore(BaseModel):
    score: int
    summary: str
    breakdown: dict[str, float]


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    type: str
    reason: str
    estimated_saving_bytes: int
    confidence: float
    risk: str
    action: str
    status: str
    file_id: int | None
    file_name: str | None = None
    file_drive_id: str | None = None
    file_web_url: str | None = None
    file_parent_id: str | None = None
    duplicate_group_id: int | None


class DuplicateGroupOut(BaseModel):
    id: int
    match_level: str
    recommended_keep_drive_id: str
    potential_recovery_bytes: int
    files: list[FileOut]


class CompressionResult(BaseModel):
    success: bool
    file_id: int
    original_size_bytes: int
    new_size_bytes: int
    saved_bytes: int
    reduction_percent: float
    message: str


class ActionHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    file_name: str
    file_drive_id: str = ""
    action: str
    original_size_bytes: int
    new_size_bytes: int
    saved_bytes: int
    status: str
    detail: str
    restorable: bool
    can_free_space: bool
    original_delete_at: datetime | None = None
    created_at: datetime


class SettingsUpdate(BaseModel):
    large_file_mb: int | None = Field(None, ge=1)
    very_large_file_mb: int | None = Field(None, ge=1)
    huge_file_mb: int | None = Field(None, ge=1)
    inactive_days: int | None = Field(None, ge=1)
    jpeg_quality: int | None = Field(None, ge=30, le=95)
    allow_format_conversion: bool | None = None
    min_saving_percent: float | None = Field(None, ge=1, le=90)
    region: str | None = None
    gmail_min_mb: int | None = Field(None, ge=1, le=100)


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    large_file_mb: int
    very_large_file_mb: int
    huge_file_mb: int
    inactive_days: int
    jpeg_quality: int
    allow_format_conversion: bool
    min_saving_percent: float
    region: str
    gmail_min_mb: int
    rules_last_run_at: datetime | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    target: str
    status: str
    progress: int
    message: str
    payload: dict
    result: dict | None
    error: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    # False while a real (non-demo) job waits with no worker process running.
    worker_online: bool = True


class RuleIn(BaseModel):
    category: Literal["video", "images", "pdf"] = "video"
    min_size_mb: int = Field(200, ge=1, le=100_000)
    min_inactive_days: int = Field(90, ge=0, le=10_000)
    enabled: bool = True
    auto_apply: bool = False


class RuleOut(RuleIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class SuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_id: int | None
    drive_id: str
    file_name: str
    category: str
    size_bytes: int
    estimated_saving_bytes: int
    status: str
    job_id: int | None
    detail: str
    created_at: datetime

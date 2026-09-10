"""Pydantic request/response schemas."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    is_google_workspace_file: bool
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
    action: str
    original_size_bytes: int
    new_size_bytes: int
    saved_bytes: int
    status: str
    detail: str
    created_at: datetime


class SettingsUpdate(BaseModel):
    large_file_mb: int | None = None
    very_large_file_mb: int | None = None
    huge_file_mb: int | None = None
    inactive_days: int | None = None
    jpeg_quality: int | None = None
    allow_format_conversion: bool | None = None
    min_saving_percent: float | None = None
    region: str | None = None


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

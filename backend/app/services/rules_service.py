"""Auto-compression rules ("videos larger than N MB, not modified in M days").

The worker evaluates each user's enabled rules once a day (RULES_HOUR_UTC).
Matching files become pending RuleSuggestions the user applies or dismisses
on the Compression page. Only a rule with auto_apply switched on (off by
default) queues compression jobs by itself — and even then each job re-checks
the rule against Drive's live metadata before touching the file.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.analyzers.compression_potential import estimate as estimate_compression
from app.analyzers.inactive import inactivity_days
from app.core.config import settings
from app.models import (
    AnalysisRun, CompressionRule, DriveFile, Job, OptimizationAction, RuleSuggestion, User, UserSettings,
)
from app.services import job_service
from app.services.drive_service import run_analysis

MB = 1024 * 1024
RULE_CATEGORIES = ("video", "images", "pdf")
# Statuses that mean "this file was already handled for this rule" — a
# dismissed suggestion is never suggested again.
_SETTLED = ("pending", "queued", "applied", "dismissed")
# Rules run on the last analysis's metadata; refresh it first if older.
ANALYSIS_MAX_AGE = timedelta(hours=20)


def matching_files(db: Session, user: User, rule: CompressionRule) -> list[DriveFile]:
    rows = db.query(DriveFile).filter(
        DriveFile.user_id == user.id, DriveFile.is_trashed.is_(False),
        DriveFile.is_google_workspace_file.is_(False), DriveFile.category == rule.category,
        DriveFile.size_bytes >= rule.min_size_mb * MB, DriveFile.inactivity_days >= rule.min_inactive_days,
    ).order_by(DriveFile.size_bytes.desc()).all()
    return rows


def evaluate_rules(db: Session, user: User, progress) -> dict:
    rules = db.query(CompressionRule).filter(
        CompressionRule.user_id == user.id, CompressionRule.enabled.is_(True)).order_by(CompressionRule.id).all()
    if not rules:
        _mark_run(db, user)
        return {"rules": 0, "new_suggestions": 0, "auto_applied": 0, "message": "No enabled rules."}

    last = db.query(func.max(AnalysisRun.completed_at)).filter(AnalysisRun.user_id == user.id).scalar()
    if last is None or job_service.utcnow() - last > ANALYSIS_MAX_AGE:
        progress(2, "Refreshing Drive metadata…")
        run_analysis(db, user, progress=progress.scaled(2, 70))

    progress(72, "Matching files against your rules…")
    # Already compressed, being compressed, or compressed and then undone by
    # the user — an auto-apply rule must not redo that every night.
    compressed = {d for (d,) in db.query(OptimizationAction.file_drive_id).filter(
        OptimizationAction.user_id == user.id, OptimizationAction.action == "compressed",
        OptimizationAction.status.in_(("success", "in_progress", "reverted")))}
    min_ratio = user.settings.min_saving_percent / 100.0
    new = 0
    for rule in rules:
        settled = {d for (d,) in db.query(RuleSuggestion.drive_id).filter(
            RuleSuggestion.user_id == user.id, RuleSuggestion.status.in_(_SETTLED))}
        for f in matching_files(db, user, rule):
            if f.drive_id in compressed or f.drive_id in settled:
                continue
            est = estimate_compression(f.category, f.extension, f.size_bytes, duration_ms=f.video_duration_ms,
                                       width=f.video_width, height=f.video_height)
            # A rule never overrides the estimate: an already-efficient video
            # isn't suggested just because it's big.
            if not est.compressible or est.estimated_ratio < min_ratio:
                continue
            db.add(RuleSuggestion(
                user_id=user.id, rule_id=rule.id, drive_id=f.drive_id, file_name=f.name, category=f.category,
                size_bytes=f.size_bytes, estimated_saving_bytes=int(f.size_bytes * est.estimated_ratio),
            ))
            settled.add(f.drive_id)
            new += 1
    _mark_run(db, user)

    auto_applied = 0
    auto_rules = [r.id for r in rules if r.auto_apply]
    if auto_rules:
        pending = db.query(RuleSuggestion).filter(
            RuleSuggestion.user_id == user.id, RuleSuggestion.status == "pending",
            RuleSuggestion.rule_id.in_(auto_rules),
        ).order_by(RuleSuggestion.estimated_saving_bytes.desc()).limit(settings.rules_max_auto_apply).all()
        for suggestion in pending:
            progress(80 + auto_applied, f"Auto-applying: queueing {suggestion.file_name}…")
            queue_suggestion(db, user, suggestion)
            auto_applied += 1

    message = f"{new} new suggestion{'s' if new != 1 else ''}"
    if auto_applied:
        message += f"; {auto_applied} queued for compression (auto-apply)"
    return {"rules": len(rules), "new_suggestions": new, "auto_applied": auto_applied, "message": message + "."}


def _mark_run(db: Session, user: User) -> None:
    user.settings.rules_last_run_at = job_service.utcnow()
    db.commit()


def queue_suggestion(db: Session, user: User, suggestion: RuleSuggestion) -> Job:
    """Start compressing a suggested file in the background."""
    kind = "compress_video" if suggestion.category == "video" else "compress_file"
    payload = {"drive_id": suggestion.drive_id, "suggestion_id": suggestion.id, "rule_id": suggestion.rule_id,
               "file_name": suggestion.file_name}
    existing = job_service.active_job(db, user, kind, suggestion.drive_id)
    job = existing or job_service.create_job(db, user, kind, payload, target=suggestion.drive_id)
    suggestion.status, suggestion.job_id, suggestion.detail = "queued", job.id, ""
    db.commit()
    if user.is_demo and not existing:
        job_service.run_job(job.id)
        db.refresh(job)
    return job


def rule_still_matches(rule: CompressionRule | None, size_bytes: int, modified_time: datetime | None) -> bool:
    """Re-checked against live Drive metadata right before an auto-applied
    (or suggested) compression: a file edited since the rule matched it is
    left alone."""
    if rule is None:
        return True
    return size_bytes >= rule.min_size_mb * MB and inactivity_days(modified_time) >= rule.min_inactive_days


# ------------------------------------------------------------------ schedule

def last_scheduled_time(now: datetime, hour: int) -> datetime:
    today = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    return today if now >= today else today - timedelta(days=1)


def schedule_due_evaluations(db: Session, now: datetime | None = None) -> int:
    """Queue an evaluate_rules job for every user whose rules haven't been
    evaluated since the most recent scheduled time. A rule created after that
    time waits for the next one (or for "Run rules now")."""
    now = now or job_service.utcnow()
    due_before = last_scheduled_time(now, settings.rules_hour_utc)
    queued = 0
    users = db.query(CompressionRule.user_id, func.min(CompressionRule.created_at)).filter(
        CompressionRule.enabled.is_(True)).group_by(CompressionRule.user_id).all()
    for user_id, first_rule_at in users:
        settings_row = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
        user = db.get(User, user_id)
        if settings_row is None or user is None:
            continue
        reference = settings_row.rules_last_run_at or first_rule_at
        if reference >= due_before or job_service.active_job(db, user, "evaluate_rules"):
            continue
        job_service.create_job(db, user, "evaluate_rules", {"trigger": "schedule"})
        queued += 1
    return queued

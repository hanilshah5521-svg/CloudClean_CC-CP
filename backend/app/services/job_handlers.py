"""What each job kind does. A handler gets (db, user, payload, progress) and
returns a JSON-safe result dict; raising marks the job failed (see
job_service.run_job)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.integrations.google_drive import get_client, parse_drive_time
from app.models import CompressionRule, DriveFile, OptimizationAction, User
from app.services import optimization_service, rules_service, video_service
from app.services.drive_service import run_analysis, summarize_run
from app.services.optimization_service import OptimizationError


def analyze(db: Session, user: User, payload: dict, progress) -> dict:
    return summarize_run(run_analysis(db, user, progress=progress))


def _target_file(db: Session, user: User, payload: dict) -> DriveFile:
    row = db.query(DriveFile).filter(
        DriveFile.user_id == user.id, DriveFile.drive_id == payload.get("drive_id", ""),
        DriveFile.is_trashed.is_(False),
    ).first()
    if row is None:
        raise OptimizationError("The file is no longer in your Drive's analysis. Re-analyze and try again.")
    return row


def _rule_skip(db: Session, user: User, payload: dict, file_row: DriveFile) -> dict | None:
    """For rule-triggered jobs: re-check the rule against Drive's live
    metadata. Returns a skipped result if the file no longer matches."""
    rule_id = payload.get("rule_id")
    rule = db.get(CompressionRule, rule_id) if rule_id else None
    if rule is None or rule.user_id != user.id:
        return None
    if user.is_demo:
        size, modified = file_row.size_bytes, file_row.modified_time
    else:
        meta = get_client(user).get_file(file_row.drive_id)
        size, modified = int(meta.get("size") or 0), parse_drive_time(meta.get("modifiedTime"))
    if rules_service.rule_still_matches(rule, size, modified):
        return None
    message = "The file changed since your rule matched it (edited recently or now smaller), so it was left as is."
    return optimization_service._result(False, file_row, file_row.size_bytes, file_row.size_bytes, message)


def compress_video(db: Session, user: User, payload: dict, progress) -> dict:
    file_row = _target_file(db, user, payload)
    return _rule_skip(db, user, payload, file_row) or video_service.compress_video(db, user, file_row, progress)


def compress_file(db: Session, user: User, payload: dict, progress) -> dict:
    file_row = _target_file(db, user, payload)
    skipped = _rule_skip(db, user, payload, file_row)
    if skipped:
        return skipped
    progress(30, "Compressing…")
    return optimization_service.compress_file(db, user, file_row)


def restore(db: Session, user: User, payload: dict, progress) -> dict:
    action = db.query(OptimizationAction).filter(
        OptimizationAction.id == payload.get("action_id"), OptimizationAction.user_id == user.id,
    ).first()
    if action is None:
        raise OptimizationError("History entry not found.")
    return optimization_service.restore_action(db, user, action, progress=progress)


def evaluate_rules(db: Session, user: User, payload: dict, progress) -> dict:
    return rules_service.evaluate_rules(db, user, progress)


HANDLERS = {
    "analyze": analyze,
    "compress_video": compress_video,
    "compress_file": compress_file,
    "restore": restore,
    "evaluate_rules": evaluate_rules,
}

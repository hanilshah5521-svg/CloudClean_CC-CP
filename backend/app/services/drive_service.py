"""Orchestrates: fetch Drive (and Gmail) metadata (real or demo) -> classify
-> analyze -> persist. This is the only place that talks to the Drive and
Gmail APIs for listing; everything downstream reads from the local DB cache
until the next explicit `POST /api/analyze` (metadata-first performance rule, spec #27)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.analyzers.compression_potential import archive_ratio
from app.analyzers.duplicates import find_duplicate_groups
from app.analyzers.naming import suggest_groups
from app.analyzers.inactive import inactivity_days
from app.integrations import demo_drive, demo_gmail
from app.integrations.gmail import GmailClient
from app.integrations.google_drive import GMAIL_SCOPE, authorized_credentials, get_client, parse_drive_time
from app.models import (
    AnalysisRun, DriveFile, DuplicateGroup, GmailMessage, OptimizationAction, OrganizeSuggestion, Recommendation,
    StorageSnapshot, User,
)
from app.recommendations.engine import RecommendationEngine
from app.utils.classify import classify, extension_of, is_google_workspace

logger = logging.getLogger("cloudclean")

_CONTAINER_MIME_TYPES = {"application/vnd.google-apps.folder", "application/vnd.google-apps.shortcut"}


def _normalize(raw: dict) -> dict:
    name = raw.get("name", "")
    mime = raw.get("mimeType", "")
    ext = extension_of(name)
    video = raw.get("videoMediaMetadata") or {}
    return {
        "drive_id": raw["id"],
        "name": name,
        "mime_type": mime,
        "extension": ext,
        "category": classify(mime, ext),
        # Workspace files (Docs/Sheets) have no `size` but do use quota.
        "size_bytes": int(raw.get("size") or raw.get("quotaBytesUsed") or 0),
        "created_time": parse_drive_time(raw.get("createdTime")),
        "modified_time": parse_drive_time(raw.get("modifiedTime")),
        "parent_id": (raw.get("parents") or [""])[0],
        "web_url": raw.get("webViewLink", ""),
        "is_google_workspace_file": is_google_workspace(mime),
        "is_trashed": bool(raw.get("trashed", False)),
        # Free from Drive metadata — enables exact-copy duplicate detection.
        "content_hash": raw.get("sha256Checksum") or raw.get("md5Checksum"),
        # Also free: lets a video's bitrate be estimated without downloading it.
        "video_width": int(video.get("width") or 0),
        "video_height": int(video.get("height") or 0),
        "video_duration_ms": int(video.get("durationMillis") or 0),
    }


def _file_row_to_dict(row: DriveFile) -> dict:
    return {
        "drive_id": row.drive_id, "name": row.name, "mime_type": row.mime_type,
        "extension": row.extension, "category": row.category, "size_bytes": row.size_bytes,
        "created_time": row.created_time, "modified_time": row.modified_time,
        "parent_id": row.parent_id, "web_url": row.web_url,
        "is_google_workspace_file": row.is_google_workspace_file, "is_trashed": row.is_trashed,
        "content_hash": row.content_hash, "video_width": row.video_width,
        "video_height": row.video_height, "video_duration_ms": row.video_duration_ms,
    }


def _no_progress(percent, message=""):
    pass


def _quota_and_files(db: Session, user: User, progress=_no_progress) -> tuple[dict, list[dict]]:
    if user.is_demo:
        # Bootstrap the deterministic fake Drive once; after that, re-analysis
        # reads back whatever state compression/trash actions have left in the
        # DB, so the demo dashboard genuinely reflects prior actions instead
        # of resetting itself every time "Analyze" is clicked.
        existing = db.query(DriveFile).filter(DriveFile.user_id == user.id).all()
        if not existing:
            files = [_normalize(r) for r in demo_drive.generate_demo_files()]
            return demo_drive.demo_quota(sum(f["size_bytes"] for f in files), 0), files
        active = [_file_row_to_dict(r) for r in existing if not r.is_trashed]
        # Trashed files keep using quota until Drive's Trash is emptied.
        trash = sum(r.size_bytes for r in existing if r.is_trashed)
        return demo_drive.demo_quota(sum(f["size_bytes"] for f in active), trash), active

    client = get_client(user)
    quota = client.storage_quota()
    files = []
    for n, r in enumerate(client.iter_all_files(), start=1):
        if not r.get("trashed") and r.get("mimeType") not in _CONTAINER_MIME_TYPES:
            files.append(_normalize(r))
        if n % 200 == 0:
            # The total isn't known up front; creep towards 60%.
            progress(5 + 55 * (1 - 1 / (1 + n / 2000)), f"Reading Drive metadata… {n} files so far")
    return quota, files


def _folders(user: User) -> tuple[dict, str]:
    """(folder id -> {"name", "parent_id"}, My Drive root id). Metadata only;
    a failure here never fails the analysis — paths then show as unknown."""
    if user.is_demo:
        return {}, "demo-root"
    try:
        client = get_client(user)
        return client.list_folders(), client.root_id()
    except Exception:
        logger.exception("Listing folders failed for user %s", user.id)
        return {}, ""


def folder_paths(folders: dict, root_id: str) -> dict[str, str]:
    """Folder id -> readable path like "My Drive / College / DAA"."""
    paths: dict[str, str] = {root_id: "My Drive"} if root_id else {}

    def path(folder_id: str, depth: int = 0) -> str:
        if folder_id in paths:
            return paths[folder_id]
        info = folders.get(folder_id)
        if info is None or depth > 50:  # not ours (e.g. shared with us) or a cycle
            return ""
        parent = path(info.get("parent_id", ""), depth + 1)
        paths[folder_id] = f"{parent} / {info['name']}" if parent else info["name"]
        return paths[folder_id]

    for folder_id in folders:
        path(folder_id)
    return paths


def _organize_suggestions(user: User, files: list[dict], folders: dict, root: str) -> list:
    """Naming-convention groups to tidy into folders; never fails the analysis."""
    try:
        return suggest_groups(files, folders, root)
    except Exception:
        logger.exception("Finding files to organize failed for user %s", user.id)
        return []


def gmail_access(user: User) -> str:
    """'demo' | 'granted' | 'not_granted' — whether Gmail can be scanned."""
    if user.is_demo:
        return "demo"
    return "granted" if GMAIL_SCOPE in (user.granted_scopes or "").split() else "not_granted"


def _scan_gmail(db: Session, user: User, now: datetime) -> list[dict] | None:
    """Fetch large-message metadata. Returns None when Gmail isn't available,
    so a Gmail problem never fails the Drive analysis."""
    access = gmail_access(user)
    if access == "not_granted":
        return None
    min_mb = user.settings.gmail_min_mb
    if access == "demo":
        trashed = {
            mid for (mid,) in db.query(GmailMessage.message_id).filter(
                GmailMessage.user_id == user.id, GmailMessage.is_trashed.is_(True))
        }
        messages = [
            m for m in demo_gmail.generate_demo_messages()
            if m["message_id"] not in trashed and m["size_bytes"] >= min_mb * 1024 * 1024
        ]
    else:
        try:
            messages = GmailClient(authorized_credentials(user)).large_messages(min_mb)
        except Exception:
            logger.exception("Gmail scan failed for user %s", user.id)
            return None
    naive_now = now.replace(tzinfo=None)
    for m in messages:
        m["inactivity_days"] = max(0, (naive_now - m["received_time"]).days) if m.get("received_time") else 0
    return messages


def run_analysis(db: Session, user: User, progress=_no_progress) -> AnalysisRun:
    """progress(percent, message) is only called before anything is written,
    so a background job may commit its progress without committing half an
    analysis."""
    progress(3, "Reading Drive metadata…")
    quota, files = _quota_and_files(db, user, progress)
    progress(60, f"Analyzing {len(files)} files for duplicates and savings…")
    settings_row = user.settings

    now = datetime.now(timezone.utc)
    for f in files:
        f["inactivity_days"] = inactivity_days(f["modified_time"], now)

    dup_groups = find_duplicate_groups(files)

    # Files not to suggest compressing: ones CloudClean already compressed, and
    # ones it tried where the real saving was too small — unless the file was
    # modified in Drive after that attempt (then it's worth measuring again).
    modified = {f["drive_id"]: f["modified_time"] for f in files}
    already_optimized = set()
    for drive_id, status, attempted_at in db.query(
            OptimizationAction.file_drive_id, OptimizationAction.status, OptimizationAction.created_at).filter(
            OptimizationAction.user_id == user.id, OptimizationAction.action == "compressed",
            OptimizationAction.status.in_(("success", "skipped"))):
        changed_since = modified.get(drive_id) and attempted_at and modified[drive_id] > attempted_at.replace(tzinfo=None)
        if status == "success" or not changed_since:
            already_optimized.add(drive_id)
    engine = RecommendationEngine(
        large_mb=settings_row.large_file_mb,
        very_large_mb=settings_row.very_large_file_mb,
        huge_mb=settings_row.huge_file_mb,
        min_saving_percent=settings_row.min_saving_percent,
        inactive_days=settings_row.inactive_days,
        already_optimized_ids=already_optimized,
    )
    recs = engine.generate_recommendations(files, dup_groups)
    score = engine.calculate_optimization_score(files, dup_groups, quota["drive_bytes"] or quota["used_bytes"])

    if gmail_access(user) != "not_granted":
        progress(70, "Scanning Gmail for large emails…")
    messages = _scan_gmail(db, user, now)
    if messages is not None:
        gmail_rec = engine.analyze_gmail(messages)
        if gmail_rec:
            recs.append(gmail_rec)

    # Replace prior cached ACTIVE state for this user — simplest correct
    # approach for a personal-Drive-scale dataset (thousands, not millions,
    # of files). Trashed rows are left alone so History/Restore keep working.
    # ponytail: full delete+recreate each analyze call, switch to per-file
    # upsert/diffing if this needs to scale to enterprise shared drives.
    progress(80, "Looking for files to organize into folders…")
    folders, root = _folders(user)
    paths = folder_paths(folders, root)
    for f in files:
        f["folder_path"] = paths.get(f.get("parent_id", ""), "")
    organize = _organize_suggestions(user, files, folders, root)

    progress(85, "Saving results…")
    db.query(Recommendation).filter(Recommendation.user_id == user.id).delete()
    db.query(DriveFile).filter(DriveFile.user_id == user.id, DriveFile.is_trashed.is_(False)).delete()
    db.query(DuplicateGroup).filter(DuplicateGroup.user_id == user.id).delete()
    if messages is not None:
        db.query(GmailMessage).filter(GmailMessage.user_id == user.id, GmailMessage.is_trashed.is_(False)).delete()
    db.flush()

    saving_by_drive_id: dict[str, int] = {}
    rec_type_by_drive_id: dict[str, str] = {}
    files_by_id = {f["drive_id"]: f for f in files}
    for r in recs:
        if r.file_id:
            saving_by_drive_id[r.file_id] = r.estimated_saving_bytes
            rec_type_by_drive_id[r.file_id] = r.type
    # Archive last: it never overlaps duplicate/compress files (see engine),
    # and for a large inactive file "archive" is more actionable than "review".
    for r in recs:
        if r.type == "archive":
            for drive_id in r.extra["file_ids"]:
                f = files_by_id[drive_id]
                rec_type_by_drive_id[drive_id] = "archive"
                saving_by_drive_id[drive_id] = int(f["size_bytes"] * archive_ratio(f["category"], f["extension"]))

    group_rows: dict[str, DuplicateGroup] = {}
    group_row_by_ref: dict[int, DuplicateGroup] = {}
    for g in dup_groups:
        row = DuplicateGroup(user_id=user.id, match_level=g.level, recommended_keep_drive_id=g.recommended_keep_drive_id)
        db.add(row)
        db.flush()
        group_row_by_ref[id(g)] = row
        for drive_id in g.drive_ids:
            group_rows[drive_id] = row

    file_rows: dict[str, DriveFile] = {}
    for f in files:
        group = group_rows.get(f["drive_id"])
        if group is None:
            rec_type = rec_type_by_drive_id.get(f["drive_id"], "keep")
        else:
            rec_type = "version" if group.match_level == "name" else "duplicate"
        if rec_type == "keep" and f["drive_id"] in already_optimized:
            rec_type = "already_optimized"
        row = DriveFile(
            user_id=user.id,
            duplicate_group_id=group.id if group else None,
            recommendation_type=rec_type,
            estimated_savings_bytes=saving_by_drive_id.get(f["drive_id"], 0),
            optimization_score=score["score"],
            risk_level="medium" if group else "low",
            **f,
        )
        db.add(row)
        file_rows[f["drive_id"]] = row
    db.flush()

    if messages is not None:
        for m in messages:
            db.add(GmailMessage(user_id=user.id, **m))

    for r in recs:
        group_row = group_row_by_ref.get(id(r.group_ref)) if r.group_ref is not None else None
        db.add(Recommendation(
            user_id=user.id,
            file_id=file_rows[r.file_id].id if r.file_id else None,
            duplicate_group_id=group_row.id if group_row else None,
            type=r.type, reason=r.reason, estimated_saving_bytes=r.estimated_saving_bytes,
            confidence=r.confidence, risk=r.risk, action=r.action,
        ))

    # Each file's bytes count toward at most one recommendation (see engine),
    # so this sum never double counts.
    total_recoverable = sum(r.estimated_saving_bytes for r in recs)
    run = AnalysisRun(
        user_id=user.id, files_analyzed=len(files),
        duplicates_found=sum(len(g.drive_ids) for g in dup_groups if not g.review_only),
        total_recoverable_bytes=total_recoverable, optimization_score=score["score"],
        score_breakdown=score["breakdown"], completed_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.query(OrganizeSuggestion).filter(OrganizeSuggestion.user_id == user.id,
                                        OrganizeSuggestion.status == "pending").delete()
    for g in organize:
        db.add(OrganizeSuggestion(
            user_id=user.id, parent_id=g.parent_id, parent_name=g.parent_name, folder_name=g.folder_name,
            existing_folder_id=g.existing_folder_id or "", pattern=g.pattern, category=g.category,
            drive_ids=g.drive_ids, names=g.names, total_bytes=g.total_bytes,
        ))
    db.add(StorageSnapshot(
        user_id=user.id, used_bytes=quota["used_bytes"], quota_bytes=quota["quota_bytes"],
        recoverable_bytes=total_recoverable, drive_bytes=quota["drive_bytes"],
        drive_trash_bytes=quota["drive_trash_bytes"], gmail_photos_bytes=quota["gmail_photos_bytes"],
    ))
    db.commit()
    return run


def summarize_run(run: AnalysisRun) -> dict:
    """The analysis summary the API returns (JSON-safe: also stored as a job result)."""
    return {
        "files_analyzed": run.files_analyzed,
        "duplicates_found": run.duplicates_found,
        "total_recoverable_bytes": run.total_recoverable_bytes,
        "optimization_score": run.optimization_score,
        "score_breakdown": run.score_breakdown,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }

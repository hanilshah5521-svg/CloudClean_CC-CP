"""Orchestrates: fetch Drive metadata (real or demo) -> classify -> analyze
-> persist. This is the only place that talks to the Drive API for listing;
everything downstream reads from the local DB cache until the next explicit
`POST /api/analyze` (metadata-first performance rule, spec #27)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.analyzers.duplicates import find_duplicate_groups
from app.analyzers.inactive import inactivity_days
from app.integrations import demo_drive
from app.integrations.google_drive import get_client, parse_drive_time
from app.models import AnalysisRun, DriveFile, DuplicateGroup, Recommendation, StorageSnapshot, User
from app.recommendations.engine import RecommendationEngine
from app.utils.classify import classify, extension_of, is_google_workspace


def _normalize(raw: dict) -> dict:
    name = raw.get("name", "")
    mime = raw.get("mimeType", "")
    ext = extension_of(name)
    return {
        "drive_id": raw["id"],
        "name": name,
        "mime_type": mime,
        "extension": ext,
        "category": classify(mime, ext),
        "size_bytes": int(raw.get("size") or 0),
        "created_time": parse_drive_time(raw.get("createdTime")),
        "modified_time": parse_drive_time(raw.get("modifiedTime")),
        "parent_id": (raw.get("parents") or [""])[0],
        "web_url": raw.get("webViewLink", ""),
        "is_google_workspace_file": is_google_workspace(mime),
        "is_trashed": bool(raw.get("trashed", False)),
    }


def _file_row_to_dict(row: DriveFile) -> dict:
    return {
        "drive_id": row.drive_id, "name": row.name, "mime_type": row.mime_type,
        "extension": row.extension, "category": row.category, "size_bytes": row.size_bytes,
        "created_time": row.created_time, "modified_time": row.modified_time,
        "parent_id": row.parent_id, "web_url": row.web_url,
        "is_google_workspace_file": row.is_google_workspace_file, "is_trashed": row.is_trashed,
    }


def _quota_and_files(db: Session, user: User) -> tuple[dict, list[dict]]:
    if user.is_demo:
        # Bootstrap the deterministic fake Drive once; after that, re-analysis
        # reads back whatever state compression/trash actions have left in the
        # DB, so the demo dashboard genuinely reflects prior actions instead
        # of resetting itself every time "Analyze" is clicked.
        existing = db.query(DriveFile).filter(DriveFile.user_id == user.id).all()
        if not existing:
            raw_files = demo_drive.generate_demo_files()
            quota = demo_drive.generate_demo_quota(raw_files)
            return quota, [_normalize(r) for r in raw_files]
        active = [_file_row_to_dict(r) for r in existing if not r.is_trashed]
        quota = {"used_bytes": sum(f["size_bytes"] for f in active), "quota_bytes": demo_drive.QUOTA_BYTES}
        return quota, active

    client = get_client(user)
    quota = client.storage_quota()
    files = [_normalize(r) for r in client.iter_all_files() if not r.get("trashed")]
    return quota, files


def run_analysis(db: Session, user: User) -> AnalysisRun:
    quota, files = _quota_and_files(db, user)
    settings_row = user.settings

    now = datetime.now(timezone.utc)
    for f in files:
        f["inactivity_days"] = inactivity_days(f["modified_time"], now)

    dup_groups = find_duplicate_groups(files)

    engine = RecommendationEngine(
        large_mb=settings_row.large_file_mb,
        very_large_mb=settings_row.very_large_file_mb,
        huge_mb=settings_row.huge_file_mb,
        min_saving_percent=settings_row.min_saving_percent,
    )
    recs = engine.generate_recommendations(files, dup_groups)
    score = engine.calculate_optimization_score(files, dup_groups, quota["used_bytes"])

    # Replace prior cached ACTIVE state for this user — simplest correct
    # approach for a personal-Drive-scale dataset (thousands, not millions,
    # of files). Trashed rows are left alone so History/Restore keep working.
    # ponytail: full delete+recreate each analyze call, switch to per-file
    # upsert/diffing if this needs to scale to enterprise shared drives.
    db.query(Recommendation).filter(Recommendation.user_id == user.id).delete()
    db.query(DriveFile).filter(DriveFile.user_id == user.id, DriveFile.is_trashed.is_(False)).delete()
    db.query(DuplicateGroup).filter(DuplicateGroup.user_id == user.id).delete()
    db.flush()

    saving_by_drive_id: dict[str, int] = {}
    rec_type_by_drive_id: dict[str, str] = {}
    for r in recs:
        if r.file_id:
            saving_by_drive_id[r.file_id] = r.estimated_saving_bytes
            rec_type_by_drive_id[r.file_id] = r.type

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
        row = DriveFile(
            user_id=user.id,
            duplicate_group_id=group_rows[f["drive_id"]].id if f["drive_id"] in group_rows else None,
            recommendation_type=rec_type_by_drive_id.get(f["drive_id"], "keep" if f["drive_id"] not in group_rows else "duplicate"),
            estimated_savings_bytes=saving_by_drive_id.get(f["drive_id"], 0),
            optimization_score=score["score"],
            risk_level="medium" if f["drive_id"] in group_rows else "low",
            **f,
        )
        db.add(row)
        file_rows[f["drive_id"]] = row
    db.flush()

    for r in recs:
        group_row = group_row_by_ref.get(id(r.group_ref)) if r.group_ref is not None else None
        db.add(Recommendation(
            user_id=user.id,
            file_id=file_rows[r.file_id].id if r.file_id else None,
            duplicate_group_id=group_row.id if group_row else None,
            type=r.type, reason=r.reason, estimated_saving_bytes=r.estimated_saving_bytes,
            confidence=r.confidence, risk=r.risk, action=r.action,
        ))

    total_recoverable = sum(r.estimated_saving_bytes for r in recs)
    run = AnalysisRun(
        user_id=user.id, files_analyzed=len(files), duplicates_found=sum(len(g.drive_ids) for g in dup_groups),
        total_recoverable_bytes=total_recoverable, optimization_score=score["score"],
        score_breakdown=score["breakdown"], completed_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.add(StorageSnapshot(
        user_id=user.id, used_bytes=quota["used_bytes"], quota_bytes=quota["quota_bytes"],
        recoverable_bytes=total_recoverable,
    ))
    db.commit()
    return run

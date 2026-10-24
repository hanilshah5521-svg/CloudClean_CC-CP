from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import DriveFile, DuplicateGroup, StorageSnapshot, User
from app.security.session import get_current_user

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90, "all": None}


@router.get("/breakdown")
def breakdown(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    by_category = (
        db.query(DriveFile.category, func.count(DriveFile.id), func.sum(DriveFile.size_bytes))
        .filter(DriveFile.user_id == user.id, DriveFile.is_trashed.is_(False))
        .group_by(DriveFile.category)
        .all()
    )
    largest = (
        db.query(DriveFile)
        .filter(DriveFile.user_id == user.id, DriveFile.is_trashed.is_(False))
        .order_by(DriveFile.size_bytes.desc())
        .limit(10)
        .all()
    )
    inactive_by_bucket = {"30+ days": 0, "90+ days": 0, "180+ days": 0, "1+ year": 0, "2+ years": 0}
    for days, size in db.query(DriveFile.inactivity_days, DriveFile.size_bytes).filter(
        DriveFile.user_id == user.id, DriveFile.is_trashed.is_(False)
    ):
        if days >= 730:
            inactive_by_bucket["2+ years"] += size
        elif days >= 365:
            inactive_by_bucket["1+ year"] += size
        elif days >= 180:
            inactive_by_bucket["180+ days"] += size
        elif days >= 90:
            inactive_by_bucket["90+ days"] += size
        elif days >= 30:
            inactive_by_bucket["30+ days"] += size

    duplicate_bytes = 0
    for g in db.query(DuplicateGroup).filter(DuplicateGroup.user_id == user.id, DuplicateGroup.match_level != "name").all():
        active = [f for f in g.files if not f.is_trashed]
        if len(active) < 2:
            continue
        keep = next((f for f in active if f.drive_id == g.recommended_keep_drive_id), active[0])
        duplicate_bytes += sum(f.size_bytes for f in active) - keep.size_bytes

    compressible_bytes = sum(
        f.estimated_savings_bytes for f in db.query(DriveFile).filter(
            DriveFile.user_id == user.id, DriveFile.is_trashed.is_(False), DriveFile.recommendation_type == "compress"
        )
    )

    return {
        "by_category": [{"category": c, "count": n, "size_bytes": int(s or 0)} for c, n, s in by_category],
        "largest_files": [{"id": f.id, "name": f.name, "size_bytes": f.size_bytes, "category": f.category} for f in largest],
        "inactive_by_bucket": inactive_by_bucket,
        "duplicate_storage_bytes": duplicate_bytes,
        "compressible_storage_bytes": compressible_bytes,
    }


@router.get("/history")
def storage_history(range: str = Query("30d", pattern="^(7d|30d|90d|all)$"), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(StorageSnapshot).filter(StorageSnapshot.user_id == user.id)
    days = RANGE_DAYS[range]
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        q = q.filter(StorageSnapshot.created_at >= cutoff.replace(tzinfo=None))
    rows = q.order_by(StorageSnapshot.created_at.asc()).all()
    return {
        "has_data": len(rows) > 0,
        "insufficient_history": len(rows) < 2,
        "points": [
            {"date": r.created_at, "used_bytes": r.used_bytes, "recoverable_bytes": r.recoverable_bytes}
            for r in rows
        ],
    }

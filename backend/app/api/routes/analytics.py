from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import DriveFile, DuplicateGroup, OptimizationAction, StorageSnapshot, User
from app.security.session import get_current_user
from app.services.account_service import AccountError, scoped_members

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90, "all": None}
GB = 1024 ** 3


def _members(db: Session, user: User, account_id: int | None) -> dict[int, User]:
    """Every linked account (the default), or just account_id."""
    try:
        return scoped_members(db, user, account_id)
    except AccountError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _duplicate_bytes(db: Session, user: User, members: dict[int, User]) -> int:
    if len(members) > 1:
        # The whole profile: the same total as the Duplicates page, where a
        # file copied into several accounts is one group (counted once).
        from app.api.routes.duplicates import profile_duplicate_groups

        return sum(g["potential_recovery_bytes"] for g in profile_duplicate_groups(db, user))
    total = 0
    for g in db.query(DuplicateGroup).filter(DuplicateGroup.user_id.in_(list(members)), DuplicateGroup.match_level != "name").all():
        active = [f for f in g.files if not f.is_trashed]
        if len(active) < 2:
            continue
        keep = next((f for f in active if f.drive_id == g.recommended_keep_drive_id), active[0])
        total += sum(f.size_bytes for f in active) - keep.size_bytes
    return total


def _latest_snapshots(db: Session, ids: list[int]) -> list[StorageSnapshot]:
    snaps = []
    for uid in ids:
        snap = db.query(StorageSnapshot).filter(StorageSnapshot.user_id == uid).order_by(StorageSnapshot.created_at.desc()).first()
        if snap:
            snaps.append(snap)
    return snaps


@router.get("/breakdown")
def breakdown(account_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    members = _members(db, user, account_id)
    ids = list(members)
    live = (DriveFile.user_id.in_(ids), DriveFile.is_trashed.is_(False))
    by_category = (
        db.query(DriveFile.category, func.count(DriveFile.id), func.sum(DriveFile.size_bytes))
        .filter(*live)
        .group_by(DriveFile.category)
        .all()
    )
    largest = db.query(DriveFile).filter(*live).order_by(DriveFile.size_bytes.desc()).limit(10).all()
    inactive_by_bucket = {"30+ days": 0, "90+ days": 0, "180+ days": 0, "1+ year": 0, "2+ years": 0}
    for days, size in db.query(DriveFile.inactivity_days, DriveFile.size_bytes).filter(*live):
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

    compressible_bytes = sum(
        f.estimated_savings_bytes for f in db.query(DriveFile).filter(*live, DriveFile.recommendation_type == "compress")
    )

    return {
        "by_category": [{"category": c, "count": n, "size_bytes": int(s or 0)} for c, n, s in by_category],
        "largest_files": [{"id": f.id, "name": f.name, "size_bytes": f.size_bytes, "category": f.category,
                           "account_email": members[f.user_id].email} for f in largest],
        "inactive_by_bucket": inactive_by_bucket,
        "duplicate_storage_bytes": _duplicate_bytes(db, user, members),
        "compressible_storage_bytes": compressible_bytes,
        "drive_trash_bytes": sum(s.drive_trash_bytes for s in _latest_snapshots(db, ids)),
    }


def _cheapest_plan(plans: list[dict], used_bytes: int) -> dict:
    """The cheapest plan that holds used_bytes (the biggest one if none does)."""
    fitting = [p for p in plans if p["storage_gb"] * GB >= used_bytes]
    return min(fitting, key=lambda p: p["price_monthly"]) if fitting else max(plans, key=lambda p: p["storage_gb"])


@router.get("/plan-impact")
def plan_impact(account_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """What CloudClean's savings are worth in money: for each personal account,
    the cheapest storage plan that fits its usage now, versus the plan it would
    need had nothing been saved (current usage + space saved by actions still in
    effect). School/work accounts are left out — their storage isn't bought per person."""
    from app.services.storage_service import load_storage_plans

    members = _members(db, user, account_id)
    plans_file = load_storage_plans()
    plans = sorted(plans_file["plans"], key=lambda p: p["storage_gb"])
    saved_by = dict(
        db.query(OptimizationAction.user_id, func.sum(OptimizationAction.saved_bytes))
        .filter(OptimizationAction.user_id.in_(list(members)), OptimizationAction.status == "success",
                OptimizationAction.action != "restored")
        .group_by(OptimizationAction.user_id)
        .all()
    )
    snaps = {s.user_id: s for s in _latest_snapshots(db, list(members))}

    accounts, monthly = [], 0
    for mid, member in members.items():
        snap = snaps.get(mid)
        if snap is None or snap.pooled:
            continue
        saved = int(saved_by.get(mid) or 0)
        now = _cheapest_plan(plans, snap.used_bytes)
        without = _cheapest_plan(plans, snap.used_bytes + saved)
        difference = max(0, without["price_monthly"] - now["price_monthly"])
        monthly += difference
        accounts.append({
            "account_id": mid, "account_email": member.email,
            "used_bytes": snap.used_bytes, "saved_bytes": saved,
            "plan_now": now, "plan_without_savings": without, "monthly_saving": difference,
            # Room left in the plan that fits now, before the next one would be needed.
            "headroom_bytes": max(0, now["storage_gb"] * GB - snap.used_bytes),
            "next_plan": next((p for p in plans if p["storage_gb"] > now["storage_gb"]), None),
        })
    return {
        "currency": plans_file["currency"], "region": plans_file["region"], "disclaimer": plans_file["disclaimer"],
        "monthly_saving": monthly, "yearly_saving": monthly * 12, "accounts": accounts,
        "pooled_accounts": sum(1 for mid in members if snaps.get(mid) is not None and snaps[mid].pooled),
    }


@router.get("/history")
def storage_history(range: str = Query("30d", pattern="^(7d|30d|90d|all)$"), account_id: int | None = None,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Storage used at each scan. Across several accounts, each day's point adds
    up every account's latest scan as of that day."""
    members = _members(db, user, account_id)
    rows = (
        db.query(StorageSnapshot)
        .filter(StorageSnapshot.user_id.in_(list(members)))
        .order_by(StorageSnapshot.created_at.asc())
        .all()
    )
    if len(members) == 1:
        points = [{"date": r.created_at, "used_bytes": r.used_bytes, "recoverable_bytes": r.recoverable_bytes} for r in rows]
    else:
        latest: dict[int, StorageSnapshot] = {}
        by_day: dict = {}
        for r in rows:
            latest[r.user_id] = r
            by_day[r.created_at.date()] = {
                "date": r.created_at,
                "used_bytes": sum(s.used_bytes for s in latest.values()),
                "recoverable_bytes": sum(s.recoverable_bytes for s in latest.values()),
            }
        points = list(by_day.values())
    days = RANGE_DAYS[range]
    if days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
        points = [p for p in points if p["date"] >= cutoff]
    return {
        "has_data": len(points) > 0,
        "insufficient_history": len(points) < 2,
        "points": points,
    }

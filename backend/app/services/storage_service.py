"""Storage overview + savings calculator. Pricing is loaded from a JSON
config file (data/storage_plans.json) so it can be updated without touching
code — and it is only ever shown as an "effective equivalent cost", never
claimed as Google's actual per-GB billing rate."""
import json
from functools import lru_cache

from sqlalchemy.orm import Session

from app.core.config import DATA_DIR
from app.models import StorageSnapshot, User

FREE_QUOTA_BYTES = 15 * 1024 ** 3


@lru_cache
def load_storage_plans() -> dict:
    with open(DATA_DIR / "storage_plans.json") as f:
        return json.load(f)


def storage_overview(db: Session, user: User) -> dict:
    snapshot = (
        db.query(StorageSnapshot)
        .filter(StorageSnapshot.user_id == user.id)
        .order_by(StorageSnapshot.created_at.desc(), StorageSnapshot.id.desc())
        .first()
    )
    if not snapshot:
        return {
            "used_bytes": 0, "quota_bytes": FREE_QUOTA_BYTES, "used_percent": 0.0,
            "remaining_bytes": FREE_QUOTA_BYTES, "recoverable_bytes": 0,
            "projected_used_bytes": 0, "projected_used_percent": 0.0,
            "drive_bytes": 0, "drive_trash_bytes": 0, "gmail_photos_bytes": 0,
        }
    used, quota, recoverable = snapshot.used_bytes, snapshot.quota_bytes, snapshot.recoverable_bytes
    # What's left once recommendations are applied AND Drive's Trash has
    # emptied (both trashed duplicates and what was already in Trash).
    projected = max(0, used - recoverable - snapshot.drive_trash_bytes)
    return {
        "used_bytes": used, "quota_bytes": quota,
        "used_percent": round(used / quota * 100, 1) if quota else 0.0,
        "remaining_bytes": max(0, quota - used),
        "recoverable_bytes": recoverable,
        "projected_used_bytes": projected,
        "projected_used_percent": round(projected / quota * 100, 1) if quota else 0.0,
        # Where the shared quota goes. Drive's Trash still counts until it is
        # emptied (automatically after 30 days); Google reports Gmail and
        # Photos only as one combined number.
        "drive_bytes": snapshot.drive_bytes,
        "drive_trash_bytes": snapshot.drive_trash_bytes,
        "gmail_photos_bytes": snapshot.gmail_photos_bytes,
    }


def savings_calculator(db: Session, user: User) -> dict:
    overview = storage_overview(db, user)
    plans = load_storage_plans()
    free_gb = next((p["storage_gb"] for p in plans["plans"] if p["price_monthly"] == 0), 15)

    next_paid = next((p for p in plans["plans"] if p["price_monthly"]), None)
    effective_cost_per_gb = None
    if next_paid:
        additional_gb = next_paid["storage_gb"] - free_gb
        if additional_gb > 0:
            effective_cost_per_gb = round(next_paid["price_monthly"] / additional_gb, 2)

    avoided_upgrade = False
    if overview["quota_bytes"]:
        quota_gb = overview["quota_bytes"] / (1024 ** 3)
        used_gb = overview["used_bytes"] / (1024 ** 3)
        projected_gb = overview["projected_used_bytes"] / (1024 ** 3)
        avoided_upgrade = used_gb > quota_gb * 0.9 and projected_gb <= quota_gb * 0.9

    return {
        **overview,
        "currency": plans["currency"],
        "region": plans["region"],
        "next_plan": next_paid,
        "effective_cost_per_gb": effective_cost_per_gb,
        "potentially_avoided_upgrade": avoided_upgrade,
        "disclaimer": plans["disclaimer"],
    }

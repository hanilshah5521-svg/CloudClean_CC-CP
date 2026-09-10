"""Inactivity analysis. Inactivity is a signal for review, never proof a
file is unnecessary — callers must use "potentially inactive" wording."""
from datetime import datetime, timezone

BUCKETS = [30, 90, 180, 365, 730]  # days


def inactivity_days(modified_time: datetime | None, now: datetime | None = None) -> int:
    if modified_time is None:
        return 0
    now = now or datetime.now(timezone.utc)
    modified = modified_time.replace(tzinfo=timezone.utc) if modified_time.tzinfo is None else modified_time
    return max(0, (now - modified).days)


def inactivity_bucket(days: int) -> str | None:
    if days >= 730:
        return "2+ years"
    if days >= 365:
        return "1+ year"
    if days >= 180:
        return "180+ days"
    if days >= 90:
        return "90+ days"
    if days >= 30:
        return "30+ days"
    return None

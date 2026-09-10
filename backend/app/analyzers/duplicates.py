"""Duplicate file detection.

Three levels, cheapest first, per the product spec:
  1. Exact/normalized filename match (same size)
  2. Size + normalized filename (handles "report (1).pdf", "report_final.pdf")
  3. Content hash (SHA-256) — used only for files a caller has already hashed
     (hashing requires downloading content, so it's opt-in / done for a
     bounded candidate set, never for the whole Drive on every analysis)

Files are only ever *grouped* here — nothing is deleted. The engine also
picks a *recommended* file to keep (most recently modified), but the caller
must always let the user override that before anything is trashed.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

_COPY_PATTERNS = [
    re.compile(r"\s*\(\d+\)$"),           # "name (1)"
    re.compile(r"[_\- ]?copy\d*$", re.I), # "name copy", "name_copy2"
    re.compile(r"[_\- ]?final\d*$", re.I),# "name_final"
    re.compile(r"^copy of\s+", re.I),     # "Copy of name"
]


def normalize_name(name: str) -> str:
    base = name.rsplit(".", 1)[0] if "." in name else name
    base = base.strip().lower()
    for pattern in _COPY_PATTERNS:
        base = pattern.sub("", base).strip()
    base = re.sub(r"[\s_\-]+", " ", base).strip()
    return base


@dataclass
class DupGroup:
    drive_ids: list[str]
    level: str  # "hash" | "size_name" | "name"
    recommended_keep_drive_id: str


def find_duplicate_groups(files: list[dict]) -> list[DupGroup]:
    """`files` items need: drive_id, name, size_bytes, modified_time, content_hash(optional)."""
    groups: list[DupGroup] = []
    consumed: set[str] = set()

    # Level 3: content hash (highest confidence)
    by_hash: dict[str, list[dict]] = defaultdict(list)
    for f in files:
        if f.get("content_hash"):
            by_hash[f["content_hash"]].append(f)
    for members in by_hash.values():
        if len(members) > 1:
            groups.append(_build_group(members, "hash"))
            consumed.update(f["drive_id"] for f in members)

    # Level 2: size + normalized name
    remaining = [f for f in files if f["drive_id"] not in consumed]
    by_size_name: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for f in remaining:
        key = (f["size_bytes"], normalize_name(f["name"]))
        if f["size_bytes"] > 0 and key[1]:
            by_size_name[key].append(f)
    for members in by_size_name.values():
        if len(members) > 1:
            groups.append(_build_group(members, "size_name"))
            consumed.update(f["drive_id"] for f in members)

    # Level 1: normalized name only, sizes differ (weaker signal — still surfaced for review)
    remaining = [f for f in files if f["drive_id"] not in consumed]
    by_name: dict[str, list[dict]] = defaultdict(list)
    for f in remaining:
        key = normalize_name(f["name"])
        if key:
            by_name[key].append(f)
    for members in by_name.values():
        if len(members) > 1:
            groups.append(_build_group(members, "name"))
            consumed.update(f["drive_id"] for f in members)

    return groups


def _build_group(members: list[dict], level: str) -> DupGroup:
    # Recommend keeping the most recently modified copy — never auto-delete.
    best = max(members, key=lambda f: f.get("modified_time") or datetime.min)
    return DupGroup(
        drive_ids=[f["drive_id"] for f in members],
        level=level,
        recommended_keep_drive_id=best["drive_id"],
    )

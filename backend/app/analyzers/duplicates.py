"""Duplicate file detection.

Three levels, highest confidence first:
  1. Content hash — Drive returns sha256Checksum/md5Checksum for every
     binary file as plain metadata, so this costs no downloads. Two files
     with the same hash are byte-for-byte identical.
  2. Size + normalized name + extension — only for files Drive gave no hash
     for (Workspace-native Docs/Sheets/Slides). If both files *have* hashes
     and the hashes differ, the contents differ, so they are never grouped
     here no matter how alike their names look.
  3. Normalized name + extension, different content — these are *versions*
     ("report.pdf" vs "report_final.pdf"), not copies. They're surfaced for
     review only: never counted as recoverable space, and the API refuses
     to bulk-trash them unless the user explicitly acknowledges that the
     contents differ.

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

# Names so generic that two files sharing one says nothing about their content.
_GENERIC_NAMES = {
    "untitled", "untitled document", "untitled spreadsheet", "untitled presentation",
    "untitled form", "untitled drawing", "image", "img", "photo", "picture", "scan",
    "document", "doc", "file", "new", "new document", "download", "screenshot",
    "video", "audio", "recording", "notes", "test",
}

# Drive containers: a "duplicate" folder or shortcut must never be trashed —
# trashing a folder trashes everything inside it.
_EXCLUDED_MIME_TYPES = {"application/vnd.google-apps.folder", "application/vnd.google-apps.shortcut"}

REVIEW_ONLY_LEVELS = {"name"}


def normalize_name(name: str) -> str:
    base = name.rsplit(".", 1)[0] if "." in name else name
    base = base.strip().lower()
    for pattern in _COPY_PATTERNS:
        base = pattern.sub("", base).strip()
    base = re.sub(r"[\s_\-]+", " ", base).strip()
    return base


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


@dataclass
class DupGroup:
    drive_ids: list[str]
    level: str  # "hash" | "size_name" | "name"
    recommended_keep_drive_id: str

    @property
    def review_only(self) -> bool:
        """True when members are different content (versions), not copies."""
        return self.level in REVIEW_ONLY_LEVELS


def find_duplicate_groups(files: list[dict]) -> list[DupGroup]:
    """`files` items need: drive_id, name, size_bytes, modified_time,
    content_hash (optional), mime_type (optional)."""
    groups: list[DupGroup] = []
    candidates = [f for f in files if f.get("mime_type") not in _EXCLUDED_MIME_TYPES]
    consumed: set[str] = set()

    # Level 1: content hash (exact copies)
    by_hash: dict[str, list[dict]] = defaultdict(list)
    for f in candidates:
        if f.get("content_hash"):
            by_hash[f["content_hash"]].append(f)
    for members in by_hash.values():
        if len(members) > 1:
            groups.append(_build_group(members, "hash"))
            consumed.update(f["drive_id"] for f in members)

    # Level 2: size + normalized name, only where no hash is available
    by_size_name: dict[tuple[int, str, str], list[dict]] = defaultdict(list)
    for f in candidates:
        if f["drive_id"] in consumed or f.get("content_hash"):
            continue
        key = (f["size_bytes"], normalize_name(f["name"]), _ext(f["name"]))
        if f["size_bytes"] > 0 and key[1]:
            by_size_name[key].append(f)
    for members in by_size_name.values():
        if len(members) > 1:
            groups.append(_build_group(members, "size_name"))
            consumed.update(f["drive_id"] for f in members)

    # Level 3: same normalized name + extension, different content (versions — review only)
    by_name: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for f in candidates:
        if f["drive_id"] in consumed:
            continue
        key = (normalize_name(f["name"]), _ext(f["name"]))
        if key[0] and key[0] not in _GENERIC_NAMES:
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

"""Find loose files that follow one naming convention — "Screenshot (35).png",
"Screen Recording 2026-08-01 113349.mp4", "IMG_2001.jpg", "budget_3.xlsx" —
and suggest gathering each set into one well-named folder.

A convention is a name prefix followed by a counter, date or timestamp.
Files are grouped per containing folder (never across folders) and per kind
(category), and only when at least MIN_GROUP_SIZE share the convention.
Nothing here touches Drive; organize_service applies a suggestion.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

MIN_GROUP_SIZE = 3
# A group that already makes up most of its folder (e.g. a folder of
# assignment files Q01…Q22) is organized enough; another level would only nest.
DEDICATED_FOLDER_SHARE = 0.8
MIN_PREFIX_LETTERS = 3  # "Q01_…" -> "Q" says nothing; known short ones (IMG, VID, DSC) still count

# The convention is everything before the first digit, minus trailing
# separators: "Screen Recording 2026-…" -> "Screen Recording", "IMG_2001" -> "IMG".
_PREFIX = re.compile(r"^(?P<prefix>.*?)[\s_\-.(\[]*\d")
_SEPARATORS = re.compile(r"[\s_\-.]+")

# Well-known conventions -> the folder people would name by hand.
# Keys are the normalized prefix; category limits a key to one kind of file.
_KNOWN: list[tuple[str, str | None, str]] = [
    ("screenshot", None, "Screenshots"),
    ("screen shot", None, "Screenshots"),
    ("screen recording", None, "Screen Recordings"),
    ("screenrecorder", None, "Screen Recordings"),
    ("screen record", None, "Screen Recordings"),
    ("recording", "audio", "Recordings"),
    ("img", "images", "Photos"),
    ("image", "images", "Photos"),
    ("photo", "images", "Photos"),
    ("dsc", "images", "Photos"),
    ("dscn", "images", "Photos"),
    ("pxl", "images", "Photos"),
    ("pic", "images", "Photos"),
    ("img", "video", "Videos"),
    ("vid", "video", "Videos"),
    ("video", "video", "Videos"),
    ("mov", "video", "Videos"),
    ("pxl", "video", "Videos"),
    ("scan", None, "Scans"),
    ("scanned", None, "Scans"),
    ("camscanner", None, "Scans"),
    ("doc", "pdf", "Scans"),
    ("invoice", None, "Invoices"),
    ("receipt", None, "Receipts"),
    ("bill", None, "Bills"),
    ("statement", None, "Statements"),
    ("untitled document", None, "Untitled documents"),
    ("untitled spreadsheet", None, "Untitled spreadsheets"),
    ("untitled presentation", None, "Untitled presentations"),
]
_KNOWN_INDEX = {(k, c): name for k, c, name in _KNOWN}


@dataclass
class GroupSuggestion:
    parent_id: str
    parent_name: str
    folder_name: str
    existing_folder_id: str | None  # a sibling folder with that name already exists
    pattern: str  # shown to the user, e.g. "Screenshot (…).png"
    category: str
    drive_ids: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    total_bytes: int = 0


def convention(name: str) -> str | None:
    """The naming convention's prefix, or None if the name has no counter/date."""
    stem = name.rsplit(".", 1)[0] if "." in name else name
    m = _PREFIX.match(stem)
    if not m:
        return None
    prefix = m.group("prefix").strip(" _-.([")
    return prefix if re.search(r"[A-Za-z]", prefix) else None


def normalize(prefix: str) -> str:
    return _SEPARATORS.sub(" ", prefix).strip().lower()


def folder_name_for(prefix: str, category: str) -> str:
    key = normalize(prefix)
    known = _KNOWN_INDEX.get((key, category)) or _KNOWN_INDEX.get((key, None))
    if known:
        return known
    words = _SEPARATORS.sub(" ", prefix).strip().split(" ")
    words[0] = words[0][:1].upper() + words[0][1:]
    words[-1] = _plural(words[-1])
    return " ".join(words)


def _plural(word: str) -> str:
    lower = word.lower()
    if lower.endswith("s"):
        return word
    if lower.endswith(("x", "z", "ch", "sh")):
        return word + "es"
    if lower.endswith("y") and len(lower) > 1 and lower[-2] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def suggest_groups(files: list[dict], folders: dict[str, dict], root_id: str,
                   min_size: int = MIN_GROUP_SIZE) -> list[GroupSuggestion]:
    """files: dicts with drive_id, name, category, parent_id, size_bytes.
    folders: folder id -> {"name", "parent_id"} for the user's folders.
    root_id: the My Drive root folder's id."""
    clusters: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for f in files:
        if f.get("is_trashed") or not f.get("parent_id"):
            continue
        prefix = convention(f["name"])
        if prefix:
            clusters[(f["parent_id"], normalize(prefix), f.get("category", "other"))].append({**f, "_prefix": prefix})

    per_parent: dict[str, int] = defaultdict(int)
    for f in files:
        if not f.get("is_trashed") and f.get("parent_id"):
            per_parent[f["parent_id"]] += 1

    children: dict[str, dict[str, str]] = defaultdict(dict)  # parent -> lowercase folder name -> id
    for folder_id, info in folders.items():
        children[info.get("parent_id", "")][info["name"].strip().lower()] = folder_id

    out = []
    for (parent_id, key, category), members in clusters.items():
        if len(members) < min_size:
            continue
        known = (key, category) in _KNOWN_INDEX or (key, None) in _KNOWN_INDEX
        if not known and len(re.sub(r"[^a-z]", "", key)) < MIN_PREFIX_LETTERS:
            continue
        if parent_id != root_id and len(members) >= DEDICATED_FOLDER_SHARE * per_parent[parent_id]:
            continue  # these files already are the folder's contents
        name = folder_name_for(members[0]["_prefix"], category)
        parent_name = "My Drive" if parent_id == root_id else folders.get(parent_id, {}).get("name", "a folder")
        if parent_name.strip().lower() == name.lower():
            continue  # already organized: they live in a folder with exactly that name
        members.sort(key=lambda f: f["name"].lower())
        example = members[0]["name"]
        ext = "." + example.rsplit(".", 1)[-1] if "." in example else ""
        out.append(GroupSuggestion(
            parent_id=parent_id, parent_name=parent_name, folder_name=name,
            existing_folder_id=children[parent_id].get(name.lower()),
            pattern=f"{members[0]['_prefix']}…{ext}", category=category,
            drive_ids=[f["drive_id"] for f in members], names=[f["name"] for f in members],
            total_bytes=sum(f.get("size_bytes", 0) for f in members),
        ))
    out.sort(key=lambda g: len(g.drive_ids), reverse=True)
    return out

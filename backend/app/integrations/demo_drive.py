"""Demo Mode: deterministic, realistic fake Drive metadata.

No real Google account or network access needed. Clearly separated from the
real Drive integration — a demo user is flagged `is_demo=True` and every
demo file gets a `demo-` id prefix so it can never be mistaken for, or mixed
with, real Drive data.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone

QUOTA_BYTES = 15 * 1024 ** 3

_IMAGE_NAMES = ["vacation_photo", "screenshot", "product_shot", "wallpaper", "team_photo", "receipt_scan"]
_DOC_NAMES = ["report", "invoice", "notes", "proposal", "contract", "meeting_minutes"]
_VIDEO_NAMES = ["family_video", "tutorial_recording", "webinar", "demo_clip", "presentation_recording"]
# (width, height, bitrate in Mbps) per demo video — phone footage is
# bitrate-heavy, a screen recording already efficient. Fixed rather than
# drawn from `rng` so adding them didn't reshuffle the rest of the demo data.
_VIDEO_PROFILES = {
    "family_video": (1920, 1080, 17), "tutorial_recording": (1280, 720, 2.2), "webinar": (1280, 720, 6),
    "demo_clip": (3840, 2160, 45), "presentation_recording": (1920, 1080, 9),
}

MB = 1024 * 1024
GB = 1024 * MB


def _mk_id(seed: str) -> str:
    return "demo-" + hashlib.sha1(seed.encode()).hexdigest()[:16]


def generate_demo_files(seed: int = 42) -> list[dict]:
    """Returns Drive-API-shaped file dicts (same shape DriveClient.list_files yields)."""
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    files: list[dict] = []

    def add(name: str, mime: str, size: int, age_days: int, idx: int, content_of: str | None = None):
        """content_of: name of the file this one is a byte-identical copy of
        (gives it the same checksum, like Drive would)."""
        modified = now - timedelta(days=age_days)
        created = modified - timedelta(days=rng.randint(0, 60))
        fid = _mk_id(f"{name}-{idx}")
        entry = {
            "id": fid,
            "name": name,
            "mimeType": mime,
            "size": str(size),
            "createdTime": created.isoformat().replace("+00:00", "Z"),
            "modifiedTime": modified.isoformat().replace("+00:00", "Z"),
            "parents": ["demo-root"],
            "webViewLink": f"https://drive.google.com/file/d/{fid}/view",
            "trashed": False,
        }
        # Drive reports checksums for binary files only, never for Docs/Sheets.
        if not mime.startswith("application/vnd.google-apps."):
            entry["sha256Checksum"] = hashlib.sha256(f"content:{content_of or name}:{size}".encode()).hexdigest()
        files.append(entry)

    idx = 0
    # Large images, several with near-duplicate copies (classic "IMG (1).jpg" pattern)
    for base in _IMAGE_NAMES:
        size = rng.randint(4, 22) * MB
        age = rng.randint(10, 900)
        add(f"{base}.jpg", "image/jpeg", size, age, idx); idx += 1
        if rng.random() < 0.5:
            add(f"{base} (1).jpg", "image/jpeg", size, age - rng.randint(1, 30), idx, content_of=f"{base}.jpg"); idx += 1

    # PDFs: some exact copies under copy-style names ("report (1).pdf" — same
    # checksum), some revised versions ("notes_final.pdf" — different content)
    for base in _DOC_NAMES:
        size = rng.randint(2, 95) * MB
        age = rng.randint(5, 1000)
        add(f"{base}.pdf", "application/pdf", size, age, idx); idx += 1
        roll = rng.random()
        if roll < 0.4:
            add(f"{base} (1).pdf", "application/pdf", size, age + rng.randint(1, 20), idx, content_of=f"{base}.pdf"); idx += 1
        elif roll < 0.75:
            revised = int(size * rng.uniform(0.85, 1.15))
            add(f"{base}_final.pdf", "application/pdf", revised, max(1, age - rng.randint(1, 20)), idx); idx += 1

    # Large / huge videos, mostly inactive
    for base in _VIDEO_NAMES:
        size = rng.randint(150, 1800) * MB
        age = rng.randint(60, 900)
        add(f"{base}.mp4", "video/mp4", size, age, idx); idx += 1

    # Office documents + spreadsheets + presentations
    for i in range(10):
        size = rng.randint(1, 60) * MB
        age = rng.randint(1, 800)
        add(f"budget_{i}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", size, age, idx); idx += 1

    for i in range(8):
        size = rng.randint(5, 120) * MB
        age = rng.randint(1, 700)
        add(f"deck_{i}.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", size, age, idx); idx += 1

    # Already-compressed archives (should not be recommended for further compression)
    for i in range(6):
        size = rng.randint(50, 600) * MB
        add(f"backup_{i}.zip", "application/zip", size, rng.randint(30, 500), idx); idx += 1

    # Google Workspace native files (Docs/Sheets — no binary size, can't be "compressed")
    for i in range(15):
        add(f"Untitled document {i}", "application/vnd.google-apps.document", 0, rng.randint(1, 600), idx); idx += 1

    # Long tail of small misc files to make totals realistic
    for i in range(40):
        size = rng.randint(100 * 1024, 3 * MB)
        add(f"file_{i}.txt", "text/plain", size, rng.randint(1, 1000), idx); idx += 1

    # Scale Drive to ~12.2 GB so that, with Gmail + Photos, the shared
    # 15 GB quota sits at a realistic ~93% full. Scaling keeps copies'
    # sizes identical, so checksums stay consistent.
    total = sum(int(f["size"]) for f in files)
    target = 12.2 * GB
    if total > 0:
        scale = target / total
        for f in files:
            f["size"] = str(int(int(f["size"]) * scale))

    # Drive reports width/height/duration for videos; derive a duration that
    # gives each demo video its profile's bitrate at its final size.
    for f in files:
        profile = _VIDEO_PROFILES.get(f["name"].rsplit(".", 1)[0])
        if f["mimeType"].startswith("video/") and profile:
            width, height, mbps = profile
            f["videoMediaMetadata"] = {
                "width": width, "height": height,
                "durationMillis": str(int(int(f["size"]) * 8 / (mbps * 1_000_000) * 1000)),
            }

    return files


# Simulated Gmail + Google Photos share of the quota (Google's API reports it
# only as one number: total usage minus Drive usage).
GMAIL_PHOTOS_BYTES = int(1.7 * GB)


def demo_quota(drive_bytes: int, drive_trash_bytes: int) -> dict:
    return {
        "used_bytes": drive_bytes + drive_trash_bytes + GMAIL_PHOTOS_BYTES,
        "quota_bytes": QUOTA_BYTES,
        "drive_bytes": drive_bytes,
        "drive_trash_bytes": drive_trash_bytes,
        "gmail_photos_bytes": GMAIL_PHOTOS_BYTES,
    }

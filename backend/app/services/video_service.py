"""Video compression — the "compress_video" background job.

Same safety pattern as optimization_service.compress_file, adapted for files
far too big for memory:

1. Record Drive's current headRevisionId (the original's version).
2. Stream-download the video to a temp file on disk.
3. Re-encode it with ffmpeg (H.264 CRF ~27, AAC 128k, same resolution).
4. Verify the result with ffprobe (same duration within 1 s, video and every
   audio track present) and skip it if the saving is below the user's
   minimum — nothing is uploaded then.
5. Upload it with a resumable files.update as a new revision of the SAME
   file (ID, link, sharing and folder unchanged), verify Drive took it, and
   record the original's revision ID so History's Undo can restore it while
   Drive keeps it (~30 days).
6. Delete the temp files, whatever happened.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.analyzers.compression_potential import REENCODABLE_VIDEO_EXT
from app.compression.video import VideoError, ffmpeg_available, probe, transcode, unsupported_reason, verify
from app.core.config import settings
from app.integrations.google_drive import get_client
from app.models import DriveFile, User
from app.services.optimization_service import (
    OptimizationError, _api_error, _record_action, _result, _simulate_new_size, keep_original_for_undo,
    original_kept_forever,
)
from app.utils.workdir import free_bytes, job_workdir

logger = logging.getLogger("cloudclean")

MB = 1024 * 1024
DISK_HEADROOM_BYTES = 200 * MB


def _no_progress(percent, message=""):
    pass


def compress_video(db: Session, user: User, file_row: DriveFile, progress=_no_progress) -> dict:
    if file_row.user_id != user.id:
        raise OptimizationError("File does not belong to this user.")
    if file_row.category != "video":
        raise OptimizationError("This file isn't a video.")
    if file_row.is_trashed:
        raise OptimizationError("File is already in Trash.")
    ext = file_row.extension.lower()
    if ext not in REENCODABLE_VIDEO_EXT:
        raise OptimizationError("Only MP4, MOV and MKV videos can be re-encoded.")

    min_ratio = user.settings.min_saving_percent / 100.0

    if user.is_demo:
        progress(50, "Re-encoding (Demo Mode simulation)…")
        original_size = file_row.size_bytes
        new_size = _simulate_new_size(file_row)
        if not _worth_it(original_size, new_size, min_ratio):
            return _skip(db, user, file_row, original_size, "No meaningful saving from re-encoding.")
        action = _record_action(db, user, file_row, "compressed", original_size, new_size, "success",
                                "Demo Mode simulated video re-encoding (no real file was processed).",
                                revision_id=f"demo-rev-{file_row.drive_id}")
        keep_original_for_undo(action)
        return _succeed(db, file_row, action, new_size, "Video compressed (Demo Mode simulation).")

    if not ffmpeg_available():
        raise OptimizationError("ffmpeg isn't installed on the worker, so videos can't be re-encoded. "
                                "See README: Video compression.")
    client = get_client(user)
    meta = client.get_file(file_row.drive_id)
    old_revision = meta.get("headRevisionId")
    if not old_revision:
        raise OptimizationError("Drive didn't report a version for this file, so compression couldn't be undone "
                                "later. The file was left untouched.")
    if meta.get("trashed"):
        raise OptimizationError("File is in Trash on Drive.")
    drive_size = int(meta.get("size") or file_row.size_bytes)
    if drive_size > settings.video_max_mb * MB:
        raise OptimizationError(f"Video is larger than this deployment's {settings.video_max_mb} MB limit (VIDEO_MAX_MB).")
    mime = meta.get("mimeType") or file_row.mime_type

    with job_workdir() as work:
        # Room for the download plus an output that is (at most) as big again.
        needed = 2 * drive_size + DISK_HEADROOM_BYTES
        if free_bytes() < needed:
            raise OptimizationError(f"Not enough free disk space on the worker ({needed // MB} MB needed).")
        src, dst = work / f"original{ext}", work / f"compressed{ext}"

        progress(2, "Downloading from Drive…")
        client.download_to_file(file_row.drive_id, src, on_progress=lambda f: progress(
            2 + 33 * f, f"Downloading from Drive… {int(f * 100)}%"))
        original_size = src.stat().st_size

        try:
            source = probe(src)
            reason = unsupported_reason(source)
            if reason:
                return _skip(db, user, file_row, original_size, reason)
            progress(35, "Re-encoding…")
            transcode(src, dst, source, ext, on_progress=lambda f: progress(
                35 + 50 * f, f"Re-encoding… {int(f * 100)}%"))
            progress(85, "Checking the re-encoded video…")
            verify(source, probe(dst))
        except VideoError as exc:
            _record_action(db, user, file_row, "compressed", original_size, original_size, "failed", str(exc))
            db.commit()
            raise OptimizationError(f"{exc} The original was left untouched.") from exc

        new_size = dst.stat().st_size
        if not _worth_it(original_size, new_size, min_ratio):
            return _skip(db, user, file_row, original_size,
                         f"Re-encoding saved only {_percent(original_size, new_size)}% (your minimum is "
                         f"{user.settings.min_saving_percent:g}%), so the original was kept.")

        # Recorded before the upload, so even a crash mid-upload leaves a
        # History entry naming the original's revision.
        action = _record_action(db, user, file_row, "compressed", original_size, new_size, "in_progress",
                                "Uploading the re-encoded version…", revision_id=old_revision)
        db.commit()
        progress(86, "Uploading to Drive…")
        try:
            client.replace_content_from_file(file_row.drive_id, dst, mime, on_progress=lambda f: progress(
                86 + 12 * f, f"Uploading to Drive… {int(f * 100)}%"))
            current = client.get_file(file_row.drive_id)
        except Exception as exc:
            logger.exception("Uploading re-encoded video %s failed", file_row.drive_id)
            action.status = "failed"
            action.detail = (f"Upload failed ({_api_error(exc)}). If Drive shows a newer version, the original is "
                             f"revision {old_revision} under Manage versions in Drive.")
            db.commit()
            raise OptimizationError("Uploading the compressed video to Drive failed. Check the file's version history in Drive.") from exc
        if current.get("headRevisionId") == old_revision or int(current.get("size") or -1) != new_size:
            action.status = "failed"
            action.detail = (f"Drive did not confirm the re-encoded version. If the file changed, its original is "
                             f"revision {old_revision} under Manage versions in Drive.")
            db.commit()
            raise OptimizationError("Drive did not confirm the compressed version. Check the file's version history in Drive.")

        action.status = "success"
        action.detail = "Re-encoded (H.264, same resolution) and replaced in place: same file, link and sharing."
        note = keep_original_for_undo(action, original_kept_forever(client, file_row.drive_id, old_revision))
        return _succeed(db, file_row, action, new_size, f"Video compressed. {note}")


def _worth_it(original: int, new: int, min_ratio: float) -> bool:
    return original > 0 and new < original and (original - new) / original >= min_ratio


def _percent(original: int, new: int) -> float:
    return round(max(0, original - new) / original * 100, 1) if original else 0.0


def _skip(db, user, file_row, original_size, message) -> dict:
    _record_action(db, user, file_row, "compressed", original_size, original_size, "skipped", message)
    file_row.estimated_savings_bytes = 0
    file_row.recommendation_type = "already_optimized"  # tried; not suggested again until the file changes
    db.commit()
    return _result(False, file_row, original_size, original_size, message)


def _succeed(db, file_row, action, new_size, message) -> dict:
    original_size = action.original_size_bytes
    file_row.size_bytes = new_size
    file_row.estimated_savings_bytes = 0
    file_row.recommendation_type = "already_optimized"
    db.commit()
    return _result(True, file_row, original_size, new_size, message)

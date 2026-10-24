"""Safe optimization workflows. The rules that govern every function here:

1. Nothing is ever permanently deleted. The most destructive step is moving
   something to Drive's/Gmail's Trash, and every such step can be undone
   from History.
2. Compression replaces a file's content IN PLACE (a new revision of the
   same file), so its ID, share links, permissions and folder survive; the
   original bytes stay restorable as Drive's previous revision.
3. An original is never trashed until its replacement (e.g. a ZIP archive)
   has been uploaded AND verified on Drive.
4. Multi-file actions commit after every file, so if file 3 of 5 fails,
   files 1-2 are already recorded in History (and restorable) and the
   failure itself is recorded too — Drive and the database never disagree.

Demo Mode never talks to a real Drive — it deterministically simulates the
same before/after numbers so the dashboard tells a consistent story, and
every response is still routed through the same DB bookkeeping
(OptimizationAction, DriveFile updates) as the real path.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from app.analyzers.compression_potential import archive_ratio, estimate as estimate_compression
from app.analyzers.duplicates import REVIEW_ONLY_LEVELS
from app.compression.archive import create_zip
from app.compression.images import UnsafeToCompress, compress_jpeg, compress_png, compress_webp
from app.compression.pdf import compress_pdf
from app.integrations.gmail import GmailClient
from app.integrations.google_drive import authorized_credentials, get_client
from app.models import DriveFile, DuplicateGroup, GmailMessage, OptimizationAction, User
from app.utils.workdir import job_workdir

logger = logging.getLogger("cloudclean")

MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # safety cap on what we'll pull into memory
# Undoing a compression above this size (or of any video) streams the
# original through a temp file in the background worker instead of memory.
INLINE_RESTORE_MAX_BYTES = 32 * 1024 * 1024


class OptimizationError(Exception):
    pass


def _compress_bytes(data: bytes, category: str, extension: str, jpeg_quality: int) -> bytes:
    ext = extension.lower()
    if category == "images":
        if ext in (".jpg", ".jpeg"):
            return compress_jpeg(data, quality=jpeg_quality)
        if ext == ".png":
            return compress_png(data)
        if ext == ".webp":
            return compress_webp(data)
        raise OptimizationError("Unsupported image format for compression.")
    if category == "pdf":
        return compress_pdf(data)
    raise OptimizationError("Compression is not supported for this file type.")


def _simulate_new_size(file_row: DriveFile) -> int:
    est = estimate_compression(file_row.category, file_row.extension, file_row.size_bytes,
                               duration_ms=file_row.video_duration_ms or 0, width=file_row.video_width or 0,
                               height=file_row.video_height or 0)
    # Deterministic-but-file-specific jitter so repeated demo runs are stable per file.
    jitter = (int(hashlib.sha1(file_row.drive_id.encode()).hexdigest(), 16) % 21 - 10) / 100.0
    ratio = max(0.02, min(0.75, est.estimated_ratio + jitter * est.estimated_ratio))
    return max(0, file_row.size_bytes - int(file_row.size_bytes * ratio))


def _api_error(exc: Exception) -> str:
    if isinstance(exc, HttpError):
        return f"Google API error {exc.resp.status}: {exc.reason}"
    return str(exc) or exc.__class__.__name__


# ---------------------------------------------------------------- compression

def compress_file(db: Session, user: User, file_row: DriveFile) -> dict:
    if file_row.user_id != user.id:
        raise OptimizationError("File does not belong to this user.")
    if file_row.is_google_workspace_file:
        raise OptimizationError("Google Workspace-native files (Docs/Sheets/Slides) can't be compressed like binary files.")
    if file_row.is_trashed:
        raise OptimizationError("File is already in Trash.")
    if file_row.category == "video":
        raise OptimizationError("Videos are re-encoded by the background worker. Use Compress video on the Compression page.")

    original_size = file_row.size_bytes
    min_ratio = user.settings.min_saving_percent / 100.0

    if user.is_demo:
        new_size = _simulate_new_size(file_row)
        saved = original_size - new_size
        if original_size == 0 or saved <= 0 or (saved / original_size) < min_ratio:
            return _skip_small_saving(db, user, file_row, original_size, new_size, min_ratio)
        file_row.size_bytes = new_size
        file_row.estimated_savings_bytes = 0
        file_row.recommendation_type = "already_optimized"
        action = _record_action(db, user, file_row, "compressed", original_size, new_size, "success",
                                "Demo Mode simulated compression (no real file was processed).",
                                revision_id=f"demo-rev-{file_row.drive_id}")
        keep_original_for_undo(action)
        db.commit()
        return _result(True, file_row, original_size, new_size, "Compressed successfully (Demo Mode simulation).")

    if original_size > MAX_DOWNLOAD_BYTES:
        raise OptimizationError("File is too large for in-app compression in this deployment.")

    client = get_client(user)
    old_revision = client.get_file(file_row.drive_id).get("headRevisionId")
    if not old_revision:
        raise OptimizationError("Drive didn't report a version for this file, so compression couldn't be undone later. The file was left untouched.")

    original_bytes = client.download_file(file_row.drive_id, file_row.mime_type)
    try:
        new_bytes = _compress_bytes(original_bytes, file_row.category, file_row.extension, user.settings.jpeg_quality)
    except UnsafeToCompress as exc:
        return _skip(db, user, file_row, original_size, str(exc))
    except OptimizationError:
        _record_action(db, user, file_row, "compressed", original_size, original_size, "failed", "Unsupported format.")
        db.commit()
        raise

    new_size = len(new_bytes)
    saved = original_size - new_size
    if original_size == 0 or saved <= 0 or (saved / original_size) < min_ratio:
        return _skip_small_saving(db, user, file_row, original_size, new_size, min_ratio)

    client.replace_content(file_row.drive_id, new_bytes, file_row.mime_type)
    current = client.get_file(file_row.drive_id)
    if current.get("headRevisionId") == old_revision or int(current.get("size") or -1) != new_size:
        _record_action(db, user, file_row, "compressed", original_size, original_size, "failed",
                       f"Drive did not confirm the optimized version. If the file changed, its original is "
                       f"revision {old_revision} under Manage versions in Drive.")
        db.commit()
        raise OptimizationError("Drive did not confirm the optimized version. Check the file's version history in Drive.")

    file_row.size_bytes = new_size
    file_row.estimated_savings_bytes = 0
    file_row.recommendation_type = "already_optimized"
    action = _record_action(db, user, file_row, "compressed", original_size, new_size, "success",
                            "Replaced in place with the optimized version — same file, link and sharing.",
                            revision_id=old_revision)
    note = keep_original_for_undo(action, original_kept_forever(client, file_row.drive_id, old_revision))
    db.commit()
    return _result(True, file_row, original_size, new_size, f"Compressed successfully. {note}")


def _compressed_file_row(db: Session, user: User, action: OptimizationAction) -> DriveFile | None:
    return db.query(DriveFile).filter(
        DriveFile.user_id == user.id, DriveFile.drive_id == action.file_drive_id
    ).first()


def _restore_streams(db: Session, user: User, action: OptimizationAction) -> bool:
    file_row = _compressed_file_row(db, user, action)
    return action.original_size_bytes > INLINE_RESTORE_MAX_BYTES or (file_row is not None and file_row.category == "video")


def restore_runs_in_background(db: Session, user: User, action: OptimizationAction) -> bool:
    """Undoing a video (or other big) compression means downloading and
    re-uploading the original: too slow for an HTTP request, so the History
    route hands it to the worker as a "restore" job."""
    return (not user.is_demo and action.action == "compressed" and action.restorable
            and _restore_streams(db, user, action))


def _download_original(download):
    try:
        return download()
    except HttpError as exc:
        if exc.resp.status == 404:
            raise OptimizationError(
                "Drive no longer keeps the original version (older versions of uploaded files are kept "
                "for about 30 days). Nothing was changed."
            ) from exc
        raise


def _restore_compression(db: Session, user: User, action: OptimizationAction, progress=None) -> dict:
    file_row = _compressed_file_row(db, user, action)
    if user.is_demo:
        restored_size = action.original_size_bytes
    elif _restore_streams(db, user, action):
        # Video-sized: stream the old revision to disk, then upload it back as
        # a new revision in resumable chunks (never the whole file in memory).
        client = get_client(user)
        progress = progress or (lambda percent, message="": None)
        mime = client.get_file(action.file_drive_id).get("mimeType", "application/octet-stream")
        with job_workdir() as work:
            path = work / "original"
            _download_original(lambda: client.download_revision_to_file(
                action.file_drive_id, action.revision_id, path,
                on_progress=lambda f: progress(5 + 45 * f, f"Downloading the original version… {int(f * 100)}%")))
            client.replace_content_from_file(
                action.file_drive_id, path, mime,
                on_progress=lambda f: progress(50 + 48 * f, f"Uploading it back to Drive… {int(f * 100)}%"))
            restored_size = path.stat().st_size
    else:
        client = get_client(user)
        original = _download_original(lambda: client.download_revision(action.file_drive_id, action.revision_id))
        mime = client.get_file(action.file_drive_id).get("mimeType", "application/octet-stream")
        client.replace_content(action.file_drive_id, original, mime)
        restored_size = len(original)

    if not user.is_demo:
        _drop_restored_original(get_client(user), action)
    if file_row:
        file_row.size_bytes = restored_size
        file_row.recommendation_type = "keep"
    action.status = "reverted"
    action.original_delete_at = None
    db.add(OptimizationAction(
        user_id=user.id, file_name=action.file_name, file_drive_id=action.file_drive_id, action="restored",
        original_size_bytes=action.new_size_bytes, new_size_bytes=restored_size, saved_bytes=0,
        status="success", detail="Original (uncompressed) version restored.",
    ))
    db.commit()
    return {"success": True, "message": "Original version restored.", "restored_size_bytes": restored_size}



# ---------------------------------------------------------------- kept originals

KEEP_ORIGINAL_DAYS = 30


def original_kept_forever(client, file_id: str, revision_id: str) -> bool:
    """Whether Drive marked that version "Keep forever" (uploads from the Drive
    website and apps are). Unknown counts as yes — the safe assumption."""
    try:
        return bool(client.get_revision(file_id, revision_id).get("keepForever", True))
    except Exception:
        logger.warning("Couldn't read keepForever of %s/%s; assuming it's kept forever", file_id, revision_id)
        return True


def keep_original_for_undo(action: OptimizationAction, kept_forever: bool = True) -> str:
    """After a compression, the original stays as an older version of the
    file so it can be undone. Drive marks uploads "Keep forever" — a flag its
    API refuses to turn off — so that version would use storage forever.
    CloudClean therefore deletes it itself after KEEP_ORIGINAL_DAYS (see
    delete_expired_originals), or sooner with Free space now. Returns the note
    shown to the user."""
    if not kept_forever:
        # Drive itself removes it after 30 days, and meanwhile it doesn't count toward storage.
        note = (f"Drive keeps the original as an older version for {KEEP_ORIGINAL_DAYS} days so you can Undo; "
                f"it doesn't count toward your storage, so the space is freed now.")
        action.detail = f"{action.detail} {note}".strip()
        return note
    when = datetime.now(timezone.utc) + timedelta(days=KEEP_ORIGINAL_DAYS)
    action.original_delete_at = when.replace(tzinfo=None)
    note = (f"The original is kept until {when:%d %b %Y} so you can Undo; it still uses "
            f"{_size(action.original_size_bytes)} of storage until then. CloudClean then deletes it to free the "
            f"space — or use Free space now in History.")
    action.detail = f"{action.detail} {note}".strip()
    return note


def free_original_space(db: Session, user: User, action: OptimizationAction, automatic: bool = False) -> dict:
    """Permanently delete the kept original version of a compressed file.
    After this the compression can no longer be undone."""
    if action.user_id != user.id or not action.can_free_space:
        raise OptimizationError("There's no kept original version to delete for this action.")
    if not user.is_demo and not action.revision_id.startswith("demo-rev-"):
        get_client(user).delete_revision(action.file_drive_id, action.revision_id)
    freed = _size(action.original_size_bytes)
    how = f"automatically after {KEEP_ORIGINAL_DAYS} days" if automatic else "with Free space now"
    action.detail = (f"{action.detail} Original version deleted {how} on "
                     f"{datetime.now(timezone.utc):%d %b %Y} — {freed} freed; Undo is no longer possible.").strip()
    action.revision_id = ""
    action.original_delete_at = None
    db.commit()
    return {"success": True, "freed_bytes": action.original_size_bytes,
            "message": f"Deleted the original version of {action.file_name} — {freed} of storage freed. "
                       f"This compression can no longer be undone."}


def delete_expired_originals(db: Session) -> int:
    """Run by the worker: delete kept originals whose undo window has passed."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    due = db.query(OptimizationAction).filter(
        OptimizationAction.action == "compressed", OptimizationAction.status == "success",
        OptimizationAction.revision_id != "", OptimizationAction.original_delete_at.isnot(None),
        OptimizationAction.original_delete_at <= now,
    ).all()
    done = 0
    for action in due:
        try:
            free_original_space(db, db.get(User, action.user_id), action, automatic=True)
            done += 1
        except Exception:  # e.g. Google auth expired — retried on the next pass
            db.rollback()
            logger.exception("Deleting the kept original of action %s failed", action.id)
    return done


def _drop_restored_original(client, action: OptimizationAction) -> None:
    """After Undo, the file's current version holds the original bytes again,
    so the old "Keep forever" original is a redundant second copy using the
    same storage. Delete it — but only once Drive confirms the bytes match."""
    try:
        head_md5 = client.get_file(action.file_drive_id).get("md5Checksum")
        old_md5 = client.get_revision(action.file_drive_id, action.revision_id).get("md5Checksum")
        if head_md5 and head_md5 == old_md5:
            client.delete_revision(action.file_drive_id, action.revision_id)
    except Exception:  # the restore itself succeeded; worst case the extra copy stays
        logger.exception("Couldn't remove the redundant original after undoing action %s", action.id)

# ---------------------------------------------------------------- duplicates

def trash_duplicate_group(db: Session, user: User, group: DuplicateGroup, keep_drive_id: str,
                          acknowledge_different_content: bool = False) -> list[dict]:
    """Move every member of a duplicate group EXCEPT keep_drive_id to Trash.
    keep_drive_id is user-confirmed — the engine's recommendation is only a
    default the frontend may override."""
    if group.match_level in REVIEW_ONLY_LEVELS and not acknowledge_different_content:
        raise OptimizationError(
            "These files have different content — they're versions of a document, not copies. "
            "Confirm you've reviewed them before moving any to Trash."
        )
    client = None if user.is_demo else get_client(user)
    results = []
    for file_row in group.files:
        if file_row.drive_id == keep_drive_id or file_row.is_trashed:
            continue
        size = file_row.size_bytes
        try:
            if client:
                client.trash_file(file_row.drive_id)
        except Exception as exc:  # record and carry on with the rest
            logger.exception("Trashing %s failed", file_row.drive_id)
            _record_action(db, user, file_row, "trashed", size, size, "failed", f"Could not move to Trash: {_api_error(exc)}")
            db.commit()
            results.append(_result(False, file_row, size, size, "Could not move to Trash."))
            continue
        file_row.is_trashed = True
        _record_action(db, user, file_row, "trashed", size, 0, "success", f"Duplicate of kept file {keep_drive_id}.")
        db.commit()
        results.append(_result(True, file_row, size, 0, "Moved to Trash."))
    return results


# ---------------------------------------------------------------- archives

def archive_files(db: Session, user: User, file_rows: list[DriveFile], archive_name: str) -> dict:
    """ZIP up several files and upload the archive, then trash the originals
    — same verify-before-trash discipline as compression."""
    if not file_rows:
        raise OptimizationError("No files selected to archive.")
    if any(f.is_trashed for f in file_rows):
        raise OptimizationError("One or more selected files are already in Trash.")
    if any(f.is_google_workspace_file for f in file_rows):
        raise OptimizationError("Google Docs/Sheets/Slides have no file content to put in a ZIP. Deselect them and try again.")
    total_original = sum(f.size_bytes for f in file_rows)
    parents = {f.parent_id for f in file_rows}
    parent_id = parents.pop() if len(parents) == 1 else None  # keep the ZIP next to the files when they share a folder

    if user.is_demo:
        zip_size = sum(int(f.size_bytes * (1 - archive_ratio(f.category, f.extension))) for f in file_rows)
        uploaded_id = f"demo-zip-{hashlib.sha1(archive_name.encode()).hexdigest()[:12]}"
        client = None
    else:
        if total_original > MAX_DOWNLOAD_BYTES:
            raise OptimizationError("Selection is too large to archive in this deployment.")
        client = get_client(user)
        entries = [(f.name, client.download_file(f.drive_id, f.mime_type)) for f in file_rows]
        zip_bytes = create_zip(entries)
        zip_size = len(zip_bytes)
        uploaded = client.upload_file(archive_name, zip_bytes, "application/zip", parent_id=parent_id)
        check = client.get_file(uploaded["id"]) if client.verify_file_exists(uploaded["id"]) else {}
        if int(check.get("size") or -1) != zip_size:
            raise OptimizationError("Archive upload could not be verified — originals were left untouched.")
        uploaded_id = uploaded["id"]

    archive_row = OptimizationAction(
        user_id=user.id, file_name=archive_name, file_drive_id=uploaded_id, action="archive_created",
        original_size_bytes=0, new_size_bytes=zip_size, saved_bytes=0, status="success",
        detail=f"ZIP uploaded and verified; moving {len(file_rows)} originals to Trash"
               + (" (Demo Mode simulation)." if user.is_demo else "."),
    )
    db.add(archive_row)
    db.commit()

    trashed_bytes, failed = 0, []
    for f in file_rows:
        try:
            if client:
                client.trash_file(f.drive_id)
        except Exception as exc:
            logger.exception("Trashing archived original %s failed", f.drive_id)
            _record_action(db, user, f, "archived", f.size_bytes, f.size_bytes, "failed",
                           f"Is in {archive_name}, but could not be moved to Trash: {_api_error(exc)}")
            failed.append(f.name)
            db.commit()
            continue
        f.is_trashed = True
        trashed_bytes += f.size_bytes
        # Space saved is counted once, on the archive row below — not per file.
        _record_action(db, user, f, "archived", f.size_bytes, 0, "success",
                       f"Moved to Trash after being bundled into {archive_name}.", saved=0)
        db.commit()

    saved = max(0, trashed_bytes - zip_size)
    archive_row.original_size_bytes = trashed_bytes
    archive_row.saved_bytes = saved
    archive_row.detail = (
        f"Archived {len(file_rows) - len(failed)} of {len(file_rows)} files"
        + (f"; {len(failed)} could not be moved to Trash and are still in place." if failed else ".")
    )
    db.commit()
    return {"success": not failed, "archive_name": archive_name, "original_size_bytes": trashed_bytes,
            "new_size_bytes": zip_size, "saved_bytes": saved, "failed": failed}


# ---------------------------------------------------------------- gmail

def trash_gmail_messages(db: Session, user: User, rows: list[GmailMessage]) -> list[dict]:
    client = None if user.is_demo else GmailClient(authorized_credentials(user))
    results = []
    for row in rows:
        if row.is_trashed:
            continue
        subject = row.subject or "(no subject)"
        try:
            if client:
                client.trash(row.message_id)
        except Exception as exc:
            logger.exception("Trashing Gmail message %s failed", row.message_id)
            db.add(OptimizationAction(
                user_id=user.id, file_name=subject, file_drive_id=row.message_id, action="gmail_trashed",
                original_size_bytes=row.size_bytes, new_size_bytes=row.size_bytes, saved_bytes=0,
                status="failed", detail=f"Could not move to Gmail Trash: {_api_error(exc)}",
            ))
            db.commit()
            results.append({"message_id": row.message_id, "success": False, "saved_bytes": 0})
            continue
        row.is_trashed = True
        db.add(OptimizationAction(
            user_id=user.id, file_name=subject, file_drive_id=row.message_id, action="gmail_trashed",
            original_size_bytes=row.size_bytes, new_size_bytes=0, saved_bytes=row.size_bytes, status="success",
            detail=f"Email from {row.sender or 'unknown sender'} moved to Gmail Trash"
                   + (" (Demo Mode simulation)." if user.is_demo else "."),
        ))
        db.commit()
        results.append({"message_id": row.message_id, "success": True, "saved_bytes": row.size_bytes})
    return results


# ---------------------------------------------------------------- restore

def restore_action(db: Session, user: User, action: OptimizationAction, progress=None) -> dict:
    if not action.restorable:
        raise OptimizationError("This action can't be undone from CloudClean.")
    if action.action == "organized":
        from app.services.organize_service import undo_organize  # (organize_service doesn't import this module)
        return undo_organize(db, user, action)
    if action.action == "compressed":
        return _restore_compression(db, user, action, progress)

    if action.action == "gmail_trashed":
        if not user.is_demo:
            GmailClient(authorized_credentials(user)).untrash(action.file_drive_id)
        row = db.query(GmailMessage).filter(
            GmailMessage.user_id == user.id, GmailMessage.message_id == action.file_drive_id
        ).first()
        if row:
            row.is_trashed = False
        detail = "Email restored from Gmail Trash."
    else:  # trashed / archived — the original is in Drive's Trash
        if not user.is_demo:
            get_client(user).restore_file(action.file_drive_id)
        file_row = db.query(DriveFile).filter(
            DriveFile.user_id == user.id, DriveFile.drive_id == action.file_drive_id
        ).first()
        if file_row:
            file_row.is_trashed = False
        detail = "Restored from Trash." + (" The copy inside the ZIP archive is still there too." if action.action == "archived" else "")

    action.status = "reverted"
    db.add(OptimizationAction(
        user_id=user.id, file_name=action.file_name, file_drive_id=action.file_drive_id, action="restored",
        original_size_bytes=action.original_size_bytes, new_size_bytes=action.original_size_bytes, saved_bytes=0,
        status="success", detail=detail,
    ))
    db.commit()
    return {"success": True, "message": detail}



def _skip_small_saving(db, user, file_row, original_size: int, new_size: int, min_ratio: float) -> dict:
    """The real result wasn't worth uploading: say exactly what was measured."""
    if 0 < new_size < original_size:
        message = (f"Compressing would only save {(original_size - new_size) / original_size:.1%} "
                   f"({_size(original_size)} → {_size(new_size)}), below your {min_ratio * 100:g}% minimum — "
                   f"nothing was uploaded and the file is unchanged.")
    else:
        message = "Compressing wouldn't make this file any smaller — nothing was uploaded and the file is unchanged."
    return _skip(db, user, file_row, original_size, message)


def _skip(db, user, file_row, original_size: int, message: str) -> dict:
    """Nothing was uploaded. Record why, and mark the file as tried so it isn't
    suggested again (until it changes — see drive_service.run_analysis)."""
    _record_action(db, user, file_row, "compressed", original_size, original_size, "skipped", message)
    file_row.estimated_savings_bytes = 0
    file_row.recommendation_type = "already_optimized"
    db.commit()
    return _result(False, file_row, original_size, original_size, message)


def _size(size_bytes: int) -> str:
    return f"{size_bytes / 1024 ** 2:.1f} MB" if size_bytes >= 1024 ** 2 else f"{size_bytes / 1024:.0f} KB"

def _record_action(db, user, file_row, action, original, new, status, detail, revision_id="", saved=None):
    row = OptimizationAction(
        user_id=user.id, file_name=file_row.name, file_drive_id=file_row.drive_id, action=action,
        original_size_bytes=original, new_size_bytes=new,
        saved_bytes=max(0, original - new) if saved is None else saved,
        status=status, detail=detail, revision_id=revision_id,
    )
    db.add(row)
    return row


def _result(success: bool, file_row: DriveFile, original: int, new: int, message: str) -> dict:
    saved = max(0, original - new)
    return {
        "success": success, "file_id": file_row.id, "original_size_bytes": original,
        "new_size_bytes": new, "saved_bytes": saved,
        "reduction_percent": round(saved / original * 100, 1) if original else 0.0,
        "message": message,
    }

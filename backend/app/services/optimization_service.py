"""Safe optimization workflows. The rule that governs every function here:

    an original file is NEVER trashed until its replacement has been
    uploaded AND verified to exist on Drive.

Demo Mode never talks to a real Drive — it deterministically simulates the
same before/after numbers so the dashboard tells a consistent story, and
every response is still routed through the same DB bookkeeping (OptimizationAction,
DriveFile updates) as the real path.
"""
from __future__ import annotations

import hashlib
import random

from sqlalchemy.orm import Session

from app.analyzers.compression_potential import estimate as estimate_compression
from app.compression.archive import create_zip
from app.compression.images import compress_jpeg, compress_png, compress_webp
from app.compression.pdf import compress_pdf
from app.integrations.google_drive import get_client
from app.models import DriveFile, DuplicateGroup, OptimizationAction, User

MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # safety cap on what we'll pull into memory


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
    est = estimate_compression(file_row.category, file_row.extension, file_row.size_bytes)
    # Deterministic-but-file-specific jitter so repeated demo runs are stable per file.
    jitter = (int(hashlib.sha1(file_row.drive_id.encode()).hexdigest(), 16) % 21 - 10) / 100.0
    ratio = max(0.02, min(0.75, est.estimated_ratio + jitter * est.estimated_ratio))
    return max(0, file_row.size_bytes - int(file_row.size_bytes * ratio))


def compress_file(db: Session, user: User, file_row: DriveFile) -> dict:
    if file_row.user_id != user.id:
        raise OptimizationError("File does not belong to this user.")
    if file_row.is_google_workspace_file:
        raise OptimizationError("Google Workspace-native files (Docs/Sheets/Slides) can't be compressed like binary files.")
    if file_row.is_trashed:
        raise OptimizationError("File is already in Trash.")

    original_size = file_row.size_bytes
    min_ratio = user.settings.min_saving_percent / 100.0

    if user.is_demo:
        new_size = _simulate_new_size(file_row)
        saved = original_size - new_size
        if original_size == 0 or saved <= 0 or (saved / original_size) < min_ratio:
            _record_action(db, user, file_row, "compressed", original_size, original_size, "skipped",
                            "No meaningful optimization available.")
            return _result(False, file_row, original_size, original_size, "No meaningful optimization available.")
        file_row.size_bytes = new_size
        file_row.estimated_savings_bytes = 0
        file_row.recommendation_type = "already_optimized"
        _record_action(db, user, file_row, "compressed", original_size, new_size, "success",
                        "Demo Mode simulated compression (no real file was processed).")
        db.commit()
        return _result(True, file_row, original_size, new_size, "Compressed successfully (Demo Mode simulation).")

    if original_size > MAX_DOWNLOAD_BYTES:
        raise OptimizationError("File is too large for in-app compression in this deployment.")

    client = get_client(user)
    original_bytes = client.download_file(file_row.drive_id, file_row.mime_type)
    try:
        new_bytes = _compress_bytes(original_bytes, file_row.category, file_row.extension, user.settings.jpeg_quality)
    except OptimizationError:
        _record_action(db, user, file_row, "compressed", original_size, original_size, "failed", "Unsupported format.")
        raise

    new_size = len(new_bytes)
    saved = original_size - new_size
    if original_size == 0 or saved <= 0 or (saved / original_size) < min_ratio:
        _record_action(db, user, file_row, "compressed", original_size, original_size, "skipped",
                        "No meaningful optimization available.")
        return _result(False, file_row, original_size, original_size, "No meaningful optimization available.")

    uploaded = client.upload_file(file_row.name, new_bytes, file_row.mime_type, parent_id=file_row.parent_id or None)
    if not client.verify_file_exists(uploaded["id"]):
        raise OptimizationError("Upload could not be verified — original file was left untouched.")

    old_drive_id = file_row.drive_id
    client.trash_file(old_drive_id)

    file_row.drive_id = uploaded["id"]
    file_row.size_bytes = new_size
    file_row.web_url = uploaded.get("webViewLink", file_row.web_url)
    file_row.estimated_savings_bytes = 0
    file_row.recommendation_type = "already_optimized"
    _record_action(db, user, file_row, "compressed", original_size, new_size, "success",
                    f"Original ({old_drive_id}) moved to Trash after verified upload of optimized copy.")
    db.commit()
    return _result(True, file_row, original_size, new_size, "Compressed successfully.")


def trash_duplicate_group(db: Session, user: User, group: DuplicateGroup, keep_drive_id: str) -> list[dict]:
    """Move every member of a duplicate group EXCEPT keep_drive_id to Trash.
    keep_drive_id is user-confirmed — the engine's recommendation is only a
    default the frontend may override."""
    results = []
    for file_row in group.files:
        if file_row.drive_id == keep_drive_id:
            continue
        if user.is_demo:
            pass  # simulated — no real API call
        else:
            client = get_client(user)
            client.trash_file(file_row.drive_id)
        original_size = file_row.size_bytes
        file_row.is_trashed = True
        _record_action(db, user, file_row, "trashed", original_size, 0, "success",
                        f"Duplicate of kept file {keep_drive_id}.")
        results.append(_result(True, file_row, original_size, 0, "Moved to Trash."))
    db.commit()
    return results


def restore_action(db: Session, user: User, action: OptimizationAction) -> dict:
    if action.action != "trashed" or action.status != "success":
        raise OptimizationError("Only successfully trashed files can be restored.")
    file_row = db.query(DriveFile).filter(
        DriveFile.user_id == user.id, DriveFile.drive_id == action.file_drive_id
    ).first()
    if not file_row:
        raise OptimizationError("File no longer tracked locally — restore it from Google Drive's Trash directly.")
    if not user.is_demo:
        client = get_client(user)
        client.restore_file(file_row.drive_id)
    file_row.is_trashed = False
    action.status = "reverted"
    db.add(OptimizationAction(
        user_id=user.id, file_name=file_row.name, file_drive_id=file_row.drive_id, action="restored",
        original_size_bytes=file_row.size_bytes, new_size_bytes=file_row.size_bytes, saved_bytes=0,
        status="success", detail="Restored from Trash.",
    ))
    db.commit()
    return _result(True, file_row, file_row.size_bytes, file_row.size_bytes, "Restored from Trash.")


def archive_files(db: Session, user: User, file_rows: list[DriveFile], archive_name: str) -> dict:
    """ZIP up several files and upload the archive, then trash the originals
    — same verify-before-trash discipline as compression."""
    if not file_rows:
        raise OptimizationError("No files selected to archive.")
    total_original = sum(f.size_bytes for f in file_rows)

    if user.is_demo:
        rng = random.Random(archive_name)
        zip_size = int(total_original * rng.uniform(0.55, 0.75))
        for f in file_rows:
            f.is_trashed = True
            _record_action(db, user, f, "archived", f.size_bytes, 0, "success", f"Bundled into {archive_name} (Demo Mode simulation).")
        db.add(OptimizationAction(
            user_id=user.id, file_name=archive_name, file_drive_id="", action="archived",
            original_size_bytes=total_original, new_size_bytes=zip_size, saved_bytes=total_original - zip_size,
            status="success", detail=f"Archived {len(file_rows)} files (Demo Mode simulation).",
        ))
        db.commit()
        return {"success": True, "archive_name": archive_name, "original_size_bytes": total_original,
                "new_size_bytes": zip_size, "saved_bytes": total_original - zip_size}

    if total_original > MAX_DOWNLOAD_BYTES:
        raise OptimizationError("Selection is too large to archive in this deployment.")

    client = get_client(user)
    entries = [(f.name, client.download_file(f.drive_id, f.mime_type)) for f in file_rows]
    zip_bytes = create_zip(entries)
    uploaded = client.upload_file(archive_name, zip_bytes, "application/zip")
    if not client.verify_file_exists(uploaded["id"]):
        raise OptimizationError("Archive upload could not be verified — originals were left untouched.")

    for f in file_rows:
        client.trash_file(f.drive_id)
        f.is_trashed = True
        _record_action(db, user, f, "archived", f.size_bytes, 0, "success", f"Bundled into {archive_name}.")

    db.add(OptimizationAction(
        user_id=user.id, file_name=archive_name, file_drive_id=uploaded["id"], action="archived",
        original_size_bytes=total_original, new_size_bytes=len(zip_bytes), saved_bytes=total_original - len(zip_bytes),
        status="success", detail=f"Archived {len(file_rows)} files.",
    ))
    db.commit()
    return {"success": True, "archive_name": archive_name, "original_size_bytes": total_original,
            "new_size_bytes": len(zip_bytes), "saved_bytes": total_original - len(zip_bytes)}


def _record_action(db, user, file_row, action, original, new, status, detail):
    db.add(OptimizationAction(
        user_id=user.id, file_name=file_row.name, file_drive_id=file_row.drive_id, action=action,
        original_size_bytes=original, new_size_bytes=new, saved_bytes=max(0, original - new),
        status=status, detail=detail,
    ))


def _result(success: bool, file_row: DriveFile, original: int, new: int, message: str) -> dict:
    saved = max(0, original - new)
    return {
        "success": success, "file_id": file_row.id, "original_size_bytes": original,
        "new_size_bytes": new, "saved_bytes": saved,
        "reduction_percent": round(saved / original * 100, 1) if original else 0.0,
        "message": message,
    }

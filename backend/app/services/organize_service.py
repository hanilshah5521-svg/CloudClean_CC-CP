"""Organize: gather loose files that share a naming convention into one folder.

Files are MOVED (never copied or re-uploaded), so each keeps its ID, share
link and permissions. Every move is committed as it happens and recorded in
the History entry's undo data, so Undo can put each file back where it was.
Undo only ever trashes the folder if CloudClean created it and it is empty.
"""
from __future__ import annotations

import hashlib
import logging

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.integrations.google_drive import get_client
from app.models import DriveFile, OptimizationAction, OrganizeSuggestion, User

logger = logging.getLogger("cloudclean")

MAX_FOLDER_NAME = 120


class OrganizeError(Exception):
    pass


def list_suggestions(db: Session, user: User) -> list[dict]:
    rows = (db.query(OrganizeSuggestion)
            .filter(OrganizeSuggestion.user_id == user.id, OrganizeSuggestion.status == "pending")
            .order_by(OrganizeSuggestion.id).all())
    return [{
        "id": s.id, "folder_name": s.folder_name, "parent_name": s.parent_name, "pattern": s.pattern,
        "category": s.category, "count": len(s.drive_ids), "names": s.names[:8], "total_bytes": s.total_bytes,
        "uses_existing_folder": bool(s.existing_folder_id), "parent_id": s.parent_id,
        "existing_folder_id": s.existing_folder_id or "",
    } for s in sorted(rows, key=lambda s: len(s.drive_ids), reverse=True)]


def _suggestion(db: Session, user: User, suggestion_id: int) -> OrganizeSuggestion:
    s = db.query(OrganizeSuggestion).filter(OrganizeSuggestion.id == suggestion_id,
                                            OrganizeSuggestion.user_id == user.id).first()
    if s is None or s.status != "pending":
        raise OrganizeError("This suggestion is no longer available. Run Re-analyze to refresh suggestions.")
    return s


def dismiss(db: Session, user: User, suggestion_id: int) -> None:
    _suggestion(db, user, suggestion_id).status = "dismissed"
    db.commit()


def apply_suggestion(db: Session, user: User, suggestion_id: int, folder_name: str | None = None) -> dict:
    sug = _suggestion(db, user, suggestion_id)
    name = (folder_name or sug.folder_name).strip()
    if not name or len(name) > MAX_FOLDER_NAME:
        raise OrganizeError(f"Folder name must be 1-{MAX_FOLDER_NAME} characters.")
    rows = db.query(DriveFile).filter(
        DriveFile.user_id == user.id, DriveFile.drive_id.in_(sug.drive_ids), DriveFile.is_trashed.is_(False),
        DriveFile.parent_id == sug.parent_id,
    ).order_by(DriveFile.name).all()
    if not rows:
        raise OrganizeError("These files have moved since the last analysis. Run Re-analyze to refresh suggestions.")

    # Reuse the sibling folder only when the user kept the suggested name.
    existing = sug.existing_folder_id if sug.existing_folder_id and name.lower() == sug.folder_name.lower() else ""
    client = None if user.is_demo else get_client(user)
    if existing:
        folder_id, created = existing, False
    elif client:
        folder_id, created = client.create_folder(name, sug.parent_id), True
    else:
        folder_id, created = "demo-folder-" + hashlib.sha1(f"{user.id}:{name}".encode()).hexdigest()[:12], True

    action = OptimizationAction(
        user_id=user.id, file_name=name, file_drive_id=folder_id, action="organized",
        original_size_bytes=sum(r.size_bytes for r in rows), new_size_bytes=sum(r.size_bytes for r in rows),
        saved_bytes=0, status="in_progress", detail="Moving files…",
        undo_data={"folder_id": folder_id, "created": created, "parent_id": sug.parent_id, "moves": []},
    )
    db.add(action)
    sug.status = "applied"
    db.commit()

    failed = []
    for row in rows:
        try:
            if client:
                client.move_file(row.drive_id, folder_id, row.parent_id)
        except Exception:
            logger.exception("Moving %s into %s failed", row.drive_id, folder_id)
            failed.append(row.name)
            continue
        action.undo_data["moves"].append({"file_id": row.drive_id, "from": row.parent_id, "name": row.name})
        flag_modified(action, "undo_data")
        row.parent_id = folder_id
        db.commit()  # each move recorded as it happens

    moved = len(action.undo_data["moves"])
    where = "a new" if created else "the existing"
    action.status = "success" if moved else "failed"
    action.detail = (f"Moved {moved} file(s) named like “{sug.pattern}” from {sug.parent_name} into {where} folder "
                     f"“{name}”. Links and sharing are unchanged."
                     + (f" {len(failed)} couldn't be moved: {', '.join(failed[:5])}." if failed else "")
                     + (" (Demo Mode simulation.)" if user.is_demo else ""))
    db.commit()
    return {"success": moved > 0, "moved": moved, "failed": failed, "folder_name": name,
            "message": f"Moved {moved} file(s) into “{name}”." + (f" {len(failed)} couldn't be moved." if failed else "")}


def undo_organize(db: Session, user: User, action: OptimizationAction) -> dict:
    data = action.undo_data or {}
    folder_id = data.get("folder_id")
    client = None if user.is_demo else get_client(user)
    back, failed, still_moved = 0, [], []
    for move in data.get("moves", []):
        try:
            if client:
                client.move_file(move["file_id"], move["from"], folder_id)
        except Exception:
            logger.exception("Moving %s back failed", move["file_id"])
            failed.append(move.get("name", move["file_id"]))
            still_moved.append(move)  # a retry of Undo only tries these
            continue
        row = db.query(DriveFile).filter(DriveFile.user_id == user.id, DriveFile.drive_id == move["file_id"]).first()
        if row:
            row.parent_id = move["from"]
        back += 1
    removed_folder = False
    if data.get("created") and not failed and client:
        try:
            if client.folder_is_empty(folder_id):
                client.trash_file(folder_id)  # to Drive's Trash, never deleted outright
                removed_folder = True
        except Exception:
            logger.exception("Checking/trashing organize folder %s failed", folder_id)
    action.status = "reverted" if not failed else "success"
    if failed:
        action.undo_data = {**data, "moves": still_moved}
    message = (f"Moved {back} file(s) back to their original folder."
               + (" The empty folder CloudClean created was moved to Trash." if removed_folder else "")
               + (f" {len(failed)} couldn't be moved back: {', '.join(failed[:5])}." if failed else ""))
    db.add(OptimizationAction(
        user_id=user.id, file_name=action.file_name, file_drive_id=folder_id or "", action="restored",
        original_size_bytes=action.original_size_bytes, new_size_bytes=action.original_size_bytes, saved_bytes=0,
        status="success" if not failed else "failed", detail=message,
    ))
    db.commit()
    return {"success": not failed, "message": message}

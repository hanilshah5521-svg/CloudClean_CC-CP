"""Several Google accounts of one person, linked into one profile.

Each Google account stays its own User — its own token, scans, History and
settings — so every existing feature works per account unchanged. Linked
accounts share a profile key; the session's user is the account currently
being worked in, and the switcher just changes it. Cross-account views
(combined usage, duplicates spread over accounts) read every linked account.
"""
import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.integrations.demo_drive import LINKED_DEMO_ACCOUNTS
from app.models import (
    AnalysisRun, CompressionRule, DriveFile, DuplicateGroup, GmailMessage, Job, OptimizationAction,
    OrganizeSuggestion, Recommendation, RuleSuggestion, StorageSnapshot, User, UserSettings,
)
from app.services.optimization_service import trash_copies_across_accounts

MAX_DEMO_ACCOUNTS = 1 + len(LINKED_DEMO_ACCOUNTS)  # the main demo Drive + the extra simulated ones


class AccountError(Exception):
    pass


def linked_users(db: Session, user: User) -> list[User]:
    """Every account in user's profile (just [user] when it's on its own), oldest first."""
    if not user.profile_key:
        return [user]
    return db.query(User).filter(User.profile_key == user.profile_key).order_by(User.id).all()


def linked_user(db: Session, user: User, account_id: int) -> User:
    target = next((u for u in linked_users(db, user) if u.id == account_id), None)
    if target is None:  # another profile's account looks exactly like a missing one
        raise AccountError("Account not found in this profile.")
    return target


def link(db: Session, user: User, other: User) -> None:
    """Add other (and any accounts already linked to it) to user's profile."""
    if other.id == user.id:
        return
    if not user.profile_key:
        user.profile_key = uuid.uuid4().hex
    members = linked_users(db, other)
    for member in members:
        member.profile_key = user.profile_key
    db.commit()


def unlink(db: Session, user: User, target: User) -> None:
    """Take target out of the profile. A simulated (demo) account is deleted;
    a Google account stays connected on its own and can sign in by itself."""
    if target.id == user.id:
        raise AccountError("Switch to another account before removing this one.")
    remaining = [u for u in linked_users(db, user) if u.id != target.id]  # before target may be deleted
    if target.is_demo:
        delete_accounts(db, [target.id])
    else:
        target.profile_key = ""
    if len(remaining) <= 1:  # nothing left to link
        user.profile_key = ""
    db.commit()


def delete_accounts(db: Session, user_ids: list[int]) -> None:
    for model in (RuleSuggestion, CompressionRule, Job, Recommendation, DriveFile, DuplicateGroup, GmailMessage,
                  OptimizationAction, AnalysisRun, StorageSnapshot, OrganizeSuggestion, UserSettings):
        db.query(model).filter(model.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
    db.commit()


def add_demo_account(db: Session, user: User) -> User:
    """Demo Mode: link another simulated Google account (a college and an old
    personal one), which shares some files with the main demo account."""
    if not user.is_demo:
        raise AccountError("Simulated accounts can only be added in Demo Mode.")
    members = linked_users(db, user)
    used = {m.demo_variant for m in members}
    variant = next((v for v in sorted(LINKED_DEMO_ACCOUNTS) if v not in used), None)
    if variant is None:
        raise AccountError(f"Demo Mode has {MAX_DEMO_ACCOUNTS} simulated accounts at most.")
    label = LINKED_DEMO_ACCOUNTS[variant][0]
    base = next((m for m in members if m.demo_variant == 0), user).email
    account = User(email=f"{label}.{base}", name=f"Demo {label.title()}", is_demo=True, demo_variant=variant)
    db.add(account)
    db.flush()
    db.add(UserSettings(user_id=account.id))
    link(db, user, account)
    return account


# ---------------------------------------------------------------- summaries

def _latest(db: Session, model, user_id: int, order):
    return db.query(model).filter(model.user_id == user_id).order_by(order.desc()).first()


def account_summary(db: Session, user: User, google_configured: bool) -> dict:
    accounts = []
    for member in linked_users(db, user):
        snap = _latest(db, StorageSnapshot, member.id, StorageSnapshot.created_at)
        run = (db.query(AnalysisRun).filter(AnalysisRun.user_id == member.id, AnalysisRun.completed_at.isnot(None))
               .order_by(AnalysisRun.completed_at.desc()).first())
        accounts.append({
            "id": member.id, "email": member.email, "name": member.name, "picture_url": member.picture_url,
            "is_demo": member.is_demo, "active": member.id == user.id,
            "scanned_at": run.completed_at if run else None,
            "files": run.files_analyzed if run else 0,
            "used_bytes": snap.used_bytes if snap else None,
            "quota_bytes": snap.quota_bytes if snap else None,
            "drive_bytes": snap.drive_bytes if snap else None,
            "drive_trash_bytes": snap.drive_trash_bytes if snap else None,
            "gmail_photos_bytes": snap.gmail_photos_bytes if snap else None,
        })
    scanned = [a for a in accounts if a["quota_bytes"]]
    can_add = (len(accounts) < MAX_DEMO_ACCOUNTS) if user.is_demo else google_configured
    return {
        "active_id": user.id,
        "accounts": accounts,
        "combined": {
            "used_bytes": sum(a["used_bytes"] for a in scanned),
            "quota_bytes": sum(a["quota_bytes"] for a in scanned),
            "scanned_accounts": len(scanned),
        },
        "can_add": can_add,
        "add_kind": "simulated" if user.is_demo else "google",
    }


# ------------------------------------------------- duplicates across accounts

def _free_bytes(db: Session, member: User) -> int:
    snap = _latest(db, StorageSnapshot, member.id, StorageSnapshot.created_at)
    return (snap.quota_bytes - snap.used_bytes) if snap and snap.quota_bytes else 0


def _copy_groups(db: Session, members: list[User]) -> list[list[DriveFile]]:
    """Files with the same checksum and size in two or more linked accounts.
    Drive lists only files each account owns, so every copy counts against
    its own account's quota."""
    rows = db.query(DriveFile).filter(
        DriveFile.user_id.in_([m.id for m in members]), DriveFile.is_trashed.is_(False),
        DriveFile.content_hash.isnot(None), DriveFile.content_hash != "", DriveFile.size_bytes > 0,
    ).all()
    by_content = defaultdict(list)
    for row in rows:
        by_content[(row.content_hash, row.size_bytes)].append(row)
    return [g for g in by_content.values() if len({r.user_id for r in g}) >= 2]


def cross_account_duplicates(db: Session, user: User, account_id: int | None = None) -> dict:
    members = linked_users(db, user)
    by_id = {m.id: m for m in members}
    free = {m.id: _free_bytes(db, m) for m in members}
    groups = []
    for files in _copy_groups(db, members):
        if account_id and account_id not in {f.user_id for f in files}:
            continue
        # Default: keep the copy in the account with the most free space, so
        # removing the others relieves the fuller accounts. Newest breaks ties.
        keep = max(files, key=lambda f: (free[f.user_id], f.modified_time or datetime.min))
        removable = sum(f.size_bytes for f in files if f.id != keep.id)
        groups.append({
            "key": f"{files[0].content_hash[:16]}-{files[0].size_bytes}",
            "content_hash": files[0].content_hash,
            "size_bytes": files[0].size_bytes,
            "recommended_keep_id": keep.id,
            "removable_bytes": removable,
            "accounts": sorted({by_id[f.user_id].email for f in files}),
            "files": [{
                "id": f.id, "account_id": f.user_id, "account_email": by_id[f.user_id].email,
                "drive_id": f.drive_id, "name": f.name, "folder_path": f.folder_path, "size_bytes": f.size_bytes,
                "modified_time": f.modified_time, "mime_type": f.mime_type, "web_url": f.web_url,
                "parent_id": f.parent_id,
            } for f in sorted(files, key=lambda f: (f.user_id, f.name))],
        })
    groups.sort(key=lambda g: g["removable_bytes"], reverse=True)
    per_account = defaultdict(int)
    for g in groups:
        for f in g["files"]:
            if f["id"] != g["recommended_keep_id"]:
                per_account[f["account_id"]] += f["size_bytes"]
    return {
        "groups": groups,
        "removable_bytes": sum(g["removable_bytes"] for g in groups),
        "removable_by_account": [{"account_id": aid, "email": by_id[aid].email, "bytes": b} for aid, b in per_account.items()],
        "linked_accounts": len(members),
    }


def remove_copies(db: Session, user: User, keep_file_id: int, remove_file_ids: list[int]) -> list[dict]:
    """Move the chosen copies to Trash in their own accounts, keeping keep_file_id.
    Every file must be a copy of the kept one (same checksum and size) in a linked account."""
    members = linked_users(db, user)
    by_id = {m.id: m for m in members}
    ids = [keep_file_id, *remove_file_ids]
    rows = {r.id: r for r in db.query(DriveFile).filter(DriveFile.id.in_(ids), DriveFile.user_id.in_(list(by_id))).all()}
    if keep_file_id not in rows or any(i not in rows for i in remove_file_ids):
        raise AccountError("File not found in this profile's accounts.")
    if keep_file_id in remove_file_ids or not remove_file_ids:
        raise AccountError("Choose one copy to keep and at least one other to remove.")
    keep = rows[keep_file_id]
    if not keep.content_hash or any(
        (rows[i].content_hash, rows[i].size_bytes) != (keep.content_hash, keep.size_bytes) for i in remove_file_ids
    ):
        raise AccountError("Those files aren't identical copies (different checksum or size).")
    return trash_copies_across_accounts(db, by_id, keep, [rows[i] for i in remove_file_ids])

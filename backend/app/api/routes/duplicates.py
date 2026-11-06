from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.analyzers.duplicates import REVIEW_ONLY_LEVELS
from app.core.database import get_db
from app.models import DuplicateGroup, User
from app.security.session import get_current_user
from app.services.account_service import cross_account_duplicates, members_by_id, owner_fields
from app.services.optimization_service import OptimizationError, trash_duplicate_group

router = APIRouter(prefix="/api", tags=["duplicates"])


class TrashRequest(BaseModel):
    keep_drive_id: str
    # Required for "name" groups, whose members have different content.
    acknowledge_different_content: bool = False


@router.get("/duplicates")
def list_duplicates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return profile_duplicate_groups(db, user)


def profile_duplicate_groups(db: Session, user: User) -> list[dict]:
    """Duplicate groups in every linked account, each file labelled with its
    account. Identical copies spread over two or more accounts form one
    "cross_account" group (removed via POST /api/accounts/duplicates/remove);
    a within-account group of that same content is folded into it, so no file
    is listed twice."""
    members = members_by_id(db, user)
    cross = cross_account_duplicates(db, user)["groups"] if len(members) > 1 else []
    in_cross = {(g["content_hash"], g["size_bytes"]) for g in cross}

    groups = (
        db.query(DuplicateGroup)
        .options(joinedload(DuplicateGroup.files))
        .filter(DuplicateGroup.user_id.in_(list(members)))
        .all()
    )
    out = []
    for g in groups:
        active_files = [f for f in g.files if not f.is_trashed]
        if len(active_files) < 2:
            continue
        if g.match_level == "hash" and (active_files[0].content_hash, active_files[0].size_bytes) in in_cross:
            continue
        owner = members[g.user_id]
        keep = next((f for f in active_files if f.drive_id == g.recommended_keep_drive_id), active_files[0])
        review_only = g.match_level in REVIEW_ONLY_LEVELS
        recovery = 0 if review_only else sum(f.size_bytes for f in active_files) - keep.size_bytes
        out.append({
            "id": g.id, "kind": "account", "match_level": g.match_level, "review_only": review_only,
            "recommended_keep_drive_id": g.recommended_keep_drive_id, "recommended_keep_file_id": keep.id,
            "potential_recovery_bytes": recovery, "accounts": [owner.email], **owner_fields(owner),
            "files": [{
                "id": f.id, "drive_id": f.drive_id, "name": f.name, "size_bytes": f.size_bytes,
                "modified_time": f.modified_time, "web_url": f.web_url, "mime_type": f.mime_type,
                "content_hash": f.content_hash, "folder_path": f.folder_path, "parent_id": f.parent_id,
                **owner_fields(owner),
            } for f in active_files],
        })
    for g in cross:
        keep = next(f for f in g["files"] if f["id"] == g["recommended_keep_id"])
        out.append({
            "id": g["key"], "kind": "cross_account", "match_level": "hash", "review_only": False,
            "recommended_keep_drive_id": keep["drive_id"], "recommended_keep_file_id": keep["id"],
            "potential_recovery_bytes": g["removable_bytes"], "accounts": g["accounts"],
            "files": [{**f, "content_hash": g["content_hash"]} for f in g["files"]],
        })
    out.sort(key=lambda g: (g["review_only"], -g["potential_recovery_bytes"]))
    return out


@router.post("/duplicates/{group_id}/trash")
def trash_duplicates(group_id: int, body: TrashRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Trash a within-account group's other copies — in the account that owns
    the group (any linked account), recorded in that account's History."""
    members = members_by_id(db, user)
    group = db.query(DuplicateGroup).options(joinedload(DuplicateGroup.files)).filter(
        DuplicateGroup.id == group_id, DuplicateGroup.user_id.in_(list(members))
    ).first()
    if not group:
        raise HTTPException(status_code=404, detail="Duplicate group not found.")
    if body.keep_drive_id not in [f.drive_id for f in group.files]:
        raise HTTPException(status_code=400, detail="keep_drive_id is not a member of this group.")
    owner = members[group.user_id]
    try:
        results = trash_duplicate_group(db, owner, group, body.keep_drive_id, body.acknowledge_different_content)
    except OptimizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"trashed": results, **owner_fields(owner)}

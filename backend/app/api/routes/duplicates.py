from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.analyzers.duplicates import REVIEW_ONLY_LEVELS
from app.core.database import get_db
from app.models import DuplicateGroup, User
from app.security.session import get_current_user
from app.services.optimization_service import OptimizationError, trash_duplicate_group

router = APIRouter(prefix="/api", tags=["duplicates"])


class TrashRequest(BaseModel):
    keep_drive_id: str
    # Required for "name" groups, whose members have different content.
    acknowledge_different_content: bool = False


@router.get("/duplicates")
def list_duplicates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    groups = (
        db.query(DuplicateGroup)
        .options(joinedload(DuplicateGroup.files))
        .filter(DuplicateGroup.user_id == user.id)
        .all()
    )
    out = []
    for g in groups:
        active_files = [f for f in g.files if not f.is_trashed]
        if len(active_files) < 2:
            continue
        keep = next((f for f in active_files if f.drive_id == g.recommended_keep_drive_id), active_files[0])
        review_only = g.match_level in REVIEW_ONLY_LEVELS
        recovery = 0 if review_only else sum(f.size_bytes for f in active_files) - keep.size_bytes
        out.append({
            "id": g.id, "match_level": g.match_level, "review_only": review_only,
            "recommended_keep_drive_id": g.recommended_keep_drive_id,
            "potential_recovery_bytes": recovery,
            "files": [{
                "id": f.id, "drive_id": f.drive_id, "name": f.name, "size_bytes": f.size_bytes,
                "modified_time": f.modified_time, "web_url": f.web_url, "mime_type": f.mime_type,
                "content_hash": f.content_hash, "folder_path": f.folder_path, "parent_id": f.parent_id,
            } for f in active_files],
        })
    out.sort(key=lambda g: (g["review_only"], -g["potential_recovery_bytes"]))
    return out


@router.post("/duplicates/{group_id}/trash")
def trash_duplicates(group_id: int, body: TrashRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    group = db.query(DuplicateGroup).options(joinedload(DuplicateGroup.files)).filter(
        DuplicateGroup.id == group_id, DuplicateGroup.user_id == user.id
    ).first()
    if not group:
        raise HTTPException(status_code=404, detail="Duplicate group not found.")
    if body.keep_drive_id not in [f.drive_id for f in group.files]:
        raise HTTPException(status_code=400, detail="keep_drive_id is not a member of this group.")
    try:
        results = trash_duplicate_group(db, user, group, body.keep_drive_id, body.acknowledge_different_content)
    except OptimizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"trashed": results}

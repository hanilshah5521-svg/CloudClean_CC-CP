from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import DriveFile, User
from app.schemas import FileOut
from app.security.session import get_current_user

router = APIRouter(prefix="/api", tags=["files"])

SORT_FIELDS = {
    "size": DriveFile.size_bytes,
    "modified": DriveFile.modified_time,
    "savings": DriveFile.estimated_savings_bytes,
    "name": DriveFile.name,
}


@router.get("/files")
def list_files(
    search: str = "",
    filter: str = Query("", description="large|duplicate|compressible|inactive|archive_candidate|optimized"),
    sort: str = Query("size", description="size|modified|savings|name"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(DriveFile).filter(DriveFile.user_id == user.id, DriveFile.is_trashed.is_(False))
    if search:
        q = q.filter(DriveFile.name.ilike(f"%{search}%"))

    if filter == "duplicate":
        q = q.filter(DriveFile.duplicate_group_id.isnot(None))
    elif filter == "compressible":
        q = q.filter(DriveFile.recommendation_type == "compress")
    elif filter == "archive_candidate":
        q = q.filter(DriveFile.recommendation_type == "archive")
    elif filter == "optimized":
        q = q.filter(DriveFile.recommendation_type == "already_optimized")
    elif filter == "inactive":
        q = q.filter(DriveFile.inactivity_days >= 90)
    elif filter == "large":
        settings_row = user.settings
        q = q.filter(DriveFile.size_bytes >= settings_row.large_file_mb * 1024 * 1024)

    total = q.count()
    sort_col = SORT_FIELDS.get(sort, DriveFile.size_bytes)
    sort_col = sort_col.desc() if order == "desc" else sort_col.asc()
    rows = q.order_by(sort_col).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total, "page": page, "page_size": page_size,
        "files": [FileOut.model_validate(r).model_dump() for r in rows],
    }


@router.get("/files/{file_id}", response_model=FileOut)
def get_file(file_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(DriveFile).filter(DriveFile.id == file_id, DriveFile.user_id == user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="File not found.")
    return row

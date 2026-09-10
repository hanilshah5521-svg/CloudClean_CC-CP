from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import DriveFile, User
from app.security.session import get_current_user
from app.services.optimization_service import OptimizationError, archive_files

router = APIRouter(prefix="/api", tags=["archive"])


class ArchiveRequest(BaseModel):
    file_ids: list[int]
    archive_name: str = "cloudclean_archive.zip"


@router.post("/archive")
def archive(body: ArchiveRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not body.file_ids:
        raise HTTPException(status_code=400, detail="Select at least one file to archive.")
    rows = db.query(DriveFile).filter(DriveFile.id.in_(body.file_ids), DriveFile.user_id == user.id).all()
    if len(rows) != len(body.file_ids):
        raise HTTPException(status_code=404, detail="One or more files not found.")
    name = body.archive_name if body.archive_name.endswith(".zip") else f"{body.archive_name}.zip"
    try:
        return archive_files(db, user, rows, name)
    except OptimizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.analyzers.compression_potential import estimate as estimate_compression
from app.core.database import get_db
from app.models import DriveFile, User
from app.security.session import get_current_user
from app.services.optimization_service import OptimizationError, compress_file

router = APIRouter(prefix="/api", tags=["compression"])


@router.get("/compression/candidates")
def compression_candidates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(DriveFile).filter(
        DriveFile.user_id == user.id, DriveFile.is_trashed.is_(False),
        DriveFile.recommendation_type == "compress",
    ).order_by(DriveFile.estimated_savings_bytes.desc()).all()

    out = []
    for f in rows:
        est = estimate_compression(f.category, f.extension, f.size_bytes)
        out.append({
            "file_id": f.id, "name": f.name, "current_size_bytes": f.size_bytes,
            "file_type": f.extension or f.category,
            "estimated_optimized_size_bytes": f.size_bytes - f.estimated_savings_bytes,
            "estimated_saving_bytes": f.estimated_savings_bytes,
            "method": est.method,
            "confidence": est.confidence,
            "confidence_label": "High" if est.confidence >= 0.75 else "Medium" if est.confidence >= 0.45 else "Low",
        })
    return out


@router.post("/compression/{file_id}")
def compress(file_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    file_row = db.query(DriveFile).filter(DriveFile.id == file_id, DriveFile.user_id == user.id).first()
    if not file_row:
        raise HTTPException(status_code=404, detail="File not found.")
    try:
        return compress_file(db, user, file_row)
    except OptimizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

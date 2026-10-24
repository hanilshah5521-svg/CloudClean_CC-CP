from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.analyzers.compression_potential import REENCODABLE_VIDEO_EXT, estimate as estimate_compression
from app.api.routes.jobs import job_out
from app.compression.video import ffmpeg_available
from app.core.database import get_db
from app.models import DriveFile, Job, OptimizationAction, User
from app.security.session import get_current_user
from app.services.job_service import ACTIVE_STATUSES, submit_job
from app.services.optimization_service import OptimizationError, compress_file

router = APIRouter(prefix="/api", tags=["compression"])


def _confidence_label(confidence: float) -> str:
    return "High" if confidence >= 0.75 else "Medium" if confidence >= 0.45 else "Low"


def _estimate(f: DriveFile):
    return estimate_compression(f.category, f.extension, f.size_bytes, duration_ms=f.video_duration_ms or 0,
                                width=f.video_width or 0, height=f.video_height or 0)


def _candidates(db: Session, user: User, video: bool):
    q = db.query(DriveFile).filter(
        DriveFile.user_id == user.id, DriveFile.is_trashed.is_(False),
        DriveFile.recommendation_type == "compress",
    )
    q = q.filter(DriveFile.category == "video") if video else q.filter(DriveFile.category != "video")
    return q.order_by(DriveFile.estimated_savings_bytes.desc()).all()


@router.get("/compression/candidates")
def compression_candidates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Images and PDFs, compressed inside the request. Videos are separate
    (see /compression/video-candidates): they're re-encoded in the background."""
    out = []
    for f in _candidates(db, user, video=False):
        est = _estimate(f)
        out.append({
            "file_id": f.id, "drive_id": f.drive_id, "name": f.name, "current_size_bytes": f.size_bytes,
            "web_url": f.web_url, "parent_id": f.parent_id,
            "file_type": f.extension or f.category,
            "estimated_optimized_size_bytes": f.size_bytes - f.estimated_savings_bytes,
            "estimated_saving_bytes": f.estimated_savings_bytes,
            "method": est.method,
            "confidence": est.confidence,
            "confidence_label": _confidence_label(est.confidence),
        })
    return out


@router.get("/compression/video-candidates")
def video_candidates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = _candidates(db, user, video=True)
    active = {
        j.target: j for j in db.query(Job).filter(
            Job.user_id == user.id, Job.kind == "compress_video", Job.status.in_(ACTIVE_STATUSES))
    }
    out = []
    for f in rows:
        est = _estimate(f)
        job = active.get(f.drive_id)
        out.append({
            "file_id": f.id, "drive_id": f.drive_id, "name": f.name, "current_size_bytes": f.size_bytes,
            "web_url": f.web_url, "parent_id": f.parent_id,
            "file_type": f.extension or f.category,
            "estimated_optimized_size_bytes": f.size_bytes - f.estimated_savings_bytes,
            "estimated_saving_bytes": f.estimated_savings_bytes,
            "confidence": est.confidence, "confidence_label": _confidence_label(est.confidence),
            "duration_s": est.details.get("duration_s"), "width": f.video_width, "height": f.video_height,
            "current_kbps": est.details.get("current_kbps"), "target_kbps": est.details.get("target_kbps"),
            "job": job_out(db, job, user) if job else None,
        })
    return {"candidates": out, "not_suggested": _videos_not_suggested(db, user),
            "ffmpeg_available": user.is_demo or ffmpeg_available()}


def _videos_not_suggested(db: Session, user: User) -> list[dict]:
    """Every other video, with the reason it isn't a candidate — so a video
    the user expected to see is never silently missing."""
    rows = db.query(DriveFile).filter(
        DriveFile.user_id == user.id, DriveFile.is_trashed.is_(False), DriveFile.category == "video",
        DriveFile.recommendation_type != "compress",
    ).order_by(DriveFile.size_bytes.desc()).all()
    out = []
    for f in rows:
        est = _estimate(f)
        if f.recommendation_type == "already_optimized":
            last = (db.query(OptimizationAction).filter(
                OptimizationAction.user_id == user.id, OptimizationAction.file_drive_id == f.drive_id,
                OptimizationAction.action == "compressed").order_by(OptimizationAction.id.desc()).first())
            reason = (f"Already tried: {last.detail}" if last and last.status == "skipped"
                      else "Already compressed by CloudClean.")
        elif f.recommendation_type in ("duplicate", "version"):
            reason = "Part of a duplicate group — handle it on the Duplicates page first."
        elif not est.compressible:
            reason = est.reason
        else:
            reason = (f"Estimated saving ({est.estimated_ratio:.0%}) is below your "
                      f"{user.settings.min_saving_percent:g}% minimum (Settings).")
        out.append({"file_id": f.id, "drive_id": f.drive_id, "name": f.name, "size_bytes": f.size_bytes,
                    "web_url": f.web_url, "parent_id": f.parent_id, "reason": reason})
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


@router.post("/compression/{file_id}/video")
def compress_video(file_id: int, response: Response, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Queue a "compress_video" job (or return the one already running for
    this file). Poll GET /api/jobs/{id}; the result has the same fields as
    POST /compression/{file_id}."""
    file_row = db.query(DriveFile).filter(
        DriveFile.id == file_id, DriveFile.user_id == user.id, DriveFile.is_trashed.is_(False)).first()
    if not file_row:
        raise HTTPException(status_code=404, detail="File not found.")
    if file_row.category != "video" or file_row.extension.lower() not in REENCODABLE_VIDEO_EXT:
        raise HTTPException(status_code=400, detail="Only MP4, MOV and MKV videos can be re-encoded.")
    job = submit_job(db, user, "compress_video", {"drive_id": file_row.drive_id, "file_name": file_row.name},
                     target=file_row.drive_id)
    if job.status not in ("done", "failed"):
        response.status_code = 202
    return job_out(db, job, user)

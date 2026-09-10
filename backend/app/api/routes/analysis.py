from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import AnalysisRun, User
from app.security.session import get_current_user
from app.services.drive_service import run_analysis

router = APIRouter(prefix="/api", tags=["analysis"])


@router.post("/analyze")
def analyze(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Fetches current Drive metadata (paginated, no file content) and
    recomputes duplicates/recommendations/score. Runs in FastAPI's worker
    threadpool since this is a sync function, so it doesn't block other
    requests — no separate job queue needed for a single-user local tool."""
    try:
        run = run_analysis(db, user)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Drive analysis failed: {exc}") from exc
    return {
        "files_analyzed": run.files_analyzed,
        "duplicates_found": run.duplicates_found,
        "total_recoverable_bytes": run.total_recoverable_bytes,
        "optimization_score": run.optimization_score,
        "score_breakdown": run.score_breakdown,
        "completed_at": run.completed_at,
    }


@router.get("/analysis")
def get_latest_analysis(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = (
        db.query(AnalysisRun)
        .filter(AnalysisRun.user_id == user.id)
        .order_by(AnalysisRun.completed_at.desc())
        .first()
    )
    if not run:
        return {"analyzed": False, "message": "No analysis has been run yet. Click Analyze to get started."}
    return {
        "analyzed": True,
        "files_analyzed": run.files_analyzed,
        "duplicates_found": run.duplicates_found,
        "total_recoverable_bytes": run.total_recoverable_bytes,
        "optimization_score": run.optimization_score,
        "score_breakdown": run.score_breakdown,
        "completed_at": run.completed_at,
    }

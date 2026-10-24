from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.routes.jobs import job_out
from app.core.database import get_db
from app.models import AnalysisRun, User
from app.security.session import get_current_user
from app.services.drive_service import summarize_run
from app.services.job_service import submit_job

router = APIRouter(prefix="/api", tags=["analysis"])


@router.post("/analyze")
def analyze(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Queues an "analyze" job (fetch Drive metadata — paginated, no file
    content — then recompute duplicates/recommendations/score) and returns
    it; poll GET /api/jobs/{job_id} for progress. Already queued or running?
    That job is returned instead of a second one.

    Demo Mode runs the job inline, so the response is the finished job, with
    the analysis summary merged in (the same fields as GET /api/analysis)."""
    job = submit_job(db, user, "analyze")
    out = {**job_out(db, job, user), "job_id": job.id}
    if job.status == "done":
        out.update(job.result or {})
    else:
        response.status_code = 202
    return out


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
    return {"analyzed": True, **summarize_run(run), "completed_at": run.completed_at}

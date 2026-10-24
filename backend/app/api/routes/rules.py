from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.routes.jobs import job_out
from app.core.config import settings
from app.core.database import get_db
from app.models import CompressionRule, RuleSuggestion, User
from app.schemas import RuleIn, RuleOut, SuggestionOut
from app.security.session import get_current_user
from app.services.job_service import submit_job
from app.services.rules_service import queue_suggestion

router = APIRouter(prefix="/api/rules", tags=["rules"])

MAX_RULES = 10


def _rule(db: Session, user: User, rule_id: int) -> CompressionRule:
    rule = db.query(CompressionRule).filter(CompressionRule.id == rule_id, CompressionRule.user_id == user.id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found.")
    return rule


@router.get("")
def list_rules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rules = db.query(CompressionRule).filter(CompressionRule.user_id == user.id).order_by(CompressionRule.id).all()
    return {
        "rules": [RuleOut.model_validate(r).model_dump(mode="json") for r in rules],
        "last_run_at": user.settings.rules_last_run_at,
        "schedule_hour_utc": settings.rules_hour_utc,
        "max_auto_apply_per_run": settings.rules_max_auto_apply,
    }


@router.post("", response_model=RuleOut)
def create_rule(body: RuleIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.query(CompressionRule).filter(CompressionRule.user_id == user.id).count() >= MAX_RULES:
        raise HTTPException(status_code=400, detail=f"At most {MAX_RULES} rules per account.")
    rule = CompressionRule(user_id=user.id, **body.model_dump())
    db.add(rule)
    db.commit()
    return rule


@router.put("/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, body: RuleIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rule = _rule(db, user, rule_id)
    for field, value in body.model_dump().items():
        setattr(rule, field, value)
    db.commit()
    return rule


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Removes the rule and its still-pending suggestions. Files already
    compressed stay compressed (and restorable from History)."""
    rule = _rule(db, user, rule_id)
    db.query(RuleSuggestion).filter(
        RuleSuggestion.rule_id == rule.id, RuleSuggestion.status == "pending").delete(synchronize_session=False)
    db.query(RuleSuggestion).filter(RuleSuggestion.rule_id == rule.id).update(
        {RuleSuggestion.rule_id: None}, synchronize_session=False)
    db.delete(rule)
    db.commit()
    return {"ok": True}


@router.post("/run")
def run_rules_now(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = submit_job(db, user, "evaluate_rules", {"trigger": "manual"})
    if job.status not in ("done", "failed"):
        response.status_code = 202
    return job_out(db, job, user)


@router.get("/suggestions", response_model=list[SuggestionOut])
def list_suggestions(status: str = "open", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """status=open (pending + queued, the default), all, or one status."""
    q = db.query(RuleSuggestion).filter(RuleSuggestion.user_id == user.id)
    if status == "open":
        q = q.filter(RuleSuggestion.status.in_(("pending", "queued")))
    elif status != "all":
        q = q.filter(RuleSuggestion.status == status)
    return q.order_by(RuleSuggestion.estimated_saving_bytes.desc()).limit(200).all()


def _suggestion(db: Session, user: User, suggestion_id: int) -> RuleSuggestion:
    s = db.query(RuleSuggestion).filter(RuleSuggestion.id == suggestion_id, RuleSuggestion.user_id == user.id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Suggestion not found.")
    return s


@router.post("/suggestions/{suggestion_id}/apply")
def apply_suggestion(suggestion_id: int, response: Response, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    suggestion = _suggestion(db, user, suggestion_id)
    if suggestion.status not in ("pending", "failed", "skipped"):
        raise HTTPException(status_code=400, detail=f"This suggestion is already {suggestion.status}.")
    job = queue_suggestion(db, user, suggestion)
    if job.status not in ("done", "failed"):
        response.status_code = 202
    return job_out(db, job, user)


@router.post("/suggestions/{suggestion_id}/dismiss", response_model=SuggestionOut)
def dismiss_suggestion(suggestion_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    suggestion = _suggestion(db, user, suggestion_id)
    if suggestion.status == "queued":
        raise HTTPException(status_code=400, detail="This file is already being compressed.")
    suggestion.status = "dismissed"
    db.commit()
    return suggestion

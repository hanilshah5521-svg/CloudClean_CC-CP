from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Recommendation, User
from app.schemas import RecommendationOut
from app.security.session import get_current_user

router = APIRouter(prefix="/api", tags=["recommendations"])


@router.get("/recommendations", response_model=list[RecommendationOut])
def list_recommendations(
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Recommendation)
        .filter(Recommendation.user_id == user.id, Recommendation.status == "pending")
        .order_by(Recommendation.estimated_saving_bytes.desc())
        .limit(limit)
        .all()
    )

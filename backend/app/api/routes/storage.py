from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import User
from app.security.session import get_current_user
from app.services.storage_service import savings_calculator, storage_overview

router = APIRouter(prefix="/api", tags=["storage"])


@router.get("/storage")
def get_storage(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return storage_overview(db, user)


@router.get("/savings")
def get_savings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return savings_calculator(db, user)

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import User
from app.schemas import SettingsOut, SettingsUpdate
from app.security.session import get_current_user

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=SettingsOut)
def get_settings(user: User = Depends(get_current_user)):
    return user.settings


@router.put("/settings", response_model=SettingsOut)
def update_settings(body: SettingsUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user.settings, field, value)
    db.commit()
    return user.settings

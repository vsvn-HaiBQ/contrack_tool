from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models import User, UserSettings


def get_current_user_settings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserSettings:
    settings = db.get(UserSettings, user.id)
    if not settings:
        settings = UserSettings(user_id=user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings

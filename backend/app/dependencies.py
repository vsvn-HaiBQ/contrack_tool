from collections.abc import Callable

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.session_store import session_store
from app.db import get_db
from app.models import User
from app.modules.users.service import role_permissions


def get_optional_user(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> User | None:
    if not session_token:
        return None
    session = session_store.get(session_token)
    if not session:
        return None
    user = db.get(User, session["user_id"])
    return user


def get_current_user(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> User:
    user = get_optional_user(db=db, session_token=session_token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


def get_audit_user(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if "audit" not in role_permissions(db, user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Audit permission required")
    return user


def require_menu_permission(permission: str) -> Callable:
    def dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if permission not in role_permissions(db, user.role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Menu permission required")
        return user

    return dependency


def require_any_menu_permission(*permissions: str) -> Callable:
    def dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        assigned = set(role_permissions(db, user.role))
        if not assigned.intersection(permissions):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Menu permission required")
        return user

    return dependency


def request_meta(request: Request) -> dict[str, str | None]:
    return {
        "ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }

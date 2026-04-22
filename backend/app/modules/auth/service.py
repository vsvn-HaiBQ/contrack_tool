from fastapi import Cookie, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_session_token, verify_password
from app.core.session_store import session_store
from app.models import User
from app.schemas import LoginRequest, MessageResponse


def login_user(payload: LoginRequest, response: Response, db: Session) -> User:
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    token = create_session_token()
    session_store.set(token, {"user_id": user.id, "username": user.username})
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        max_age=settings.session_ttl_seconds,
        samesite="lax",
    )
    return user


def logout_user(response: Response, user: User, session_token: str | None) -> MessageResponse:
    if session_token:
        session_store.delete(session_token)
    response.delete_cookie(settings.session_cookie_name)
    return MessageResponse(message=f"Logged out {user.username}")

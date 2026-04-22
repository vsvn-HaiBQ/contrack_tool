from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.dependencies import get_current_user, get_optional_user
from app.models import User
from app.schemas import LoginRequest, MeResponse, MessageResponse, SetupAdminRequest, SetupStatusResponse, UserOut
from app.modules.auth.service import login_user, logout_user
from app.modules.users.service import create_user_record, validate_password, validate_username

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> User:
    return login_user(payload, response, db)


@router.post("/logout", response_model=MessageResponse)
def logout(
    response: Response,
    user: User = Depends(get_current_user),
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> MessageResponse:
    return logout_user(response, user, session_token)


@router.get("/me", response_model=MeResponse)
def me(user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)) -> MeResponse:
    return MeResponse(authenticated=bool(user), needs_setup=db.query(User).count() == 0, user=user)


@router.get("/setup-status", response_model=SetupStatusResponse)
def setup_status(db: Session = Depends(get_db)) -> SetupStatusResponse:
    user_count = db.query(User).count()
    return SetupStatusResponse(needs_setup=user_count == 0, user_count=user_count)


@router.post("/setup", response_model=UserOut)
def setup_admin(payload: SetupAdminRequest, response: Response, db: Session = Depends(get_db)) -> User:
    if db.query(User).count() > 0:
        raise HTTPException(status_code=400, detail="Initial setup has already been completed")
    try:
        username = validate_username(payload.username)
        password = validate_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user = create_user_record(db, username=username, password=password, role="admin")
    db.commit()
    db.refresh(user)
    return login_user(LoginRequest(username=username, password=password), response, db)

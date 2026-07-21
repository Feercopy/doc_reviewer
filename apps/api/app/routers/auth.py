from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_current_user
from app.models.user import User
from app.schemas.auth import AuthUserResponse, LoginRequest
from app.schemas.enums import UserStatus
from app.schemas.users import UserRead
from app.security.passwords import verify_password
from app.security.sessions import SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS, create_session_cookie_value

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=AuthUserResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> AuthUserResponse:
    user = db.execute(select(User).where(User.login == payload.login)).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid login or password")

    if user.status != UserStatus.ACTIVE.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is blocked")

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_cookie_value(user.id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return AuthUserResponse(user=user)


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(key=SESSION_COOKIE_NAME, httponly=True, samesite="lax", secure=False)
    return {"status": "ok"}


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(require_current_user)) -> User:
    return current_user

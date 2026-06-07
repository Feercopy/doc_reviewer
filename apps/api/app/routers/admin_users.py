from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_admin
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.users import PasswordReset, UserCreate, UserPatch, UserRead, UsersListResponse
from app.security.passwords import hash_password

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


def _audit(db: Session, actor: User, action: str, target: User, metadata: dict | None = None) -> None:
    db.add(
        AuditLog(
            actor_id=actor.id,
            action=action,
            entity_type="user",
            entity_id=target.id,
            metadata_=metadata or {},
        )
    )


@router.get("", response_model=UsersListResponse)
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> UsersListResponse:
    users = db.execute(select(User).order_by(User.created_at.asc())).scalars().all()
    return UsersListResponse(users=list(users))


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    user = User(
        login=payload.login,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        role=payload.role.value,
        status=payload.status.value,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Login already exists") from exc

    _audit(db, admin, "user.create", user, {"role": user.role, "status": user.status})
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserRead)
def patch_user(
    user_id: UUID,
    payload: UserPatch,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.display_name is not None and payload.display_name != user.display_name:
        _audit(
            db,
            admin,
            "user.update",
            user,
            {"display_name": {"from": user.display_name, "to": payload.display_name}},
        )
        user.display_name = payload.display_name
    if payload.role is not None and payload.role.value != user.role:
        _audit(
            db,
            admin,
            "user.role_change",
            user,
            {"role": {"from": user.role, "to": payload.role.value}},
        )
        user.role = payload.role.value
    if payload.status is not None and payload.status.value != user.status:
        action = "user.block" if payload.status.value == "blocked" else "user.unblock"
        _audit(
            db,
            admin,
            action,
            user,
            {"status": {"from": user.status, "to": payload.status.value}},
        )
        user.status = payload.status.value
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/reset-password", response_model=UserRead)
def reset_password(
    user_id: UUID,
    payload: PasswordReset,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.password_hash = hash_password(payload.password)
    _audit(db, admin, "user.password_reset", user)
    db.commit()
    db.refresh(user)
    return user

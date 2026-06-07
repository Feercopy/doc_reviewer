import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.user import User
from app.schemas.enums import Role, UserStatus
from app.security.passwords import hash_password


def ensure_admin_user(
    db: Session,
    login: str,
    password: str,
    display_name: str = "Administrator",
) -> User:
    user = db.execute(select(User).where(User.login == login)).scalar_one_or_none()
    if user is None:
        user = User(
            login=login,
            display_name=display_name,
            password_hash=hash_password(password),
            role=Role.ADMIN.value,
            status=UserStatus.ACTIVE.value,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    user.display_name = display_name
    user.role = Role.ADMIN.value
    user.status = UserStatus.ACTIVE.value
    if password:
        user.password_hash = hash_password(password)
    db.commit()
    db.refresh(user)
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update the bootstrap admin user.")
    parser.add_argument("--login", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--display-name", default="Administrator")
    args = parser.parse_args()

    with SessionLocal() as db:
        user = ensure_admin_user(db, args.login, args.password, args.display_name)
        print(f"admin user ready: {user.login}")


if __name__ == "__main__":
    main()

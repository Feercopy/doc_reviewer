from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.enums import Role, UserStatus
from app.security.passwords import hash_password


def create_user(
    db_session: Session,
    login: str,
    password: str,
    role: Role = Role.USER,
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    user = User(
        login=login,
        display_name=login.title(),
        password_hash=hash_password(password),
        role=role.value,
        status=status.value,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def login(client, login: str, password: str):
    return client.post("/auth/login", json={"login": login, "password": password})


def test_admin_can_create_and_list_user_without_password_fields(client, db_session: Session):
    create_user(db_session, "admin", "secret", Role.ADMIN)
    assert login(client, "admin", "secret").status_code == 200

    response = client.post(
        "/admin/users",
        json={
            "login": "analyst1",
            "display_name": "Analyst 1",
            "password": "initial-password",
            "role": "user",
            "status": "active",
        },
    )

    assert response.status_code == 201
    assert response.json()["login"] == "analyst1"
    assert "password" not in response.text

    list_response = client.get("/admin/users")

    assert list_response.status_code == 200
    assert {user["login"] for user in list_response.json()["users"]} == {"admin", "analyst1"}
    assert db_session.query(AuditLog).filter_by(action="user.create").count() == 1


def test_non_admin_cannot_manage_users(client, db_session):
    create_user(db_session, "analyst", "secret")
    assert login(client, "analyst", "secret").status_code == 200

    response = client.get("/admin/users")

    assert response.status_code == 403


def test_admin_can_patch_user_and_reset_password(client, db_session):
    create_user(db_session, "admin", "secret", Role.ADMIN)
    analyst = create_user(db_session, "analyst", "old-password")
    assert login(client, "admin", "secret").status_code == 200

    patch_response = client.patch(
        f"/admin/users/{analyst.id}",
        json={"role": "annotator", "status": "blocked", "display_name": "Senior Analyst"},
    )

    assert patch_response.status_code == 200
    assert patch_response.json()["role"] == "annotator"
    assert patch_response.json()["status"] == "blocked"

    reset_response = client.post(
        f"/admin/users/{analyst.id}/reset-password",
        json={"password": "new-password"},
    )

    assert reset_response.status_code == 200
    assert "password" not in reset_response.text

    client.post("/auth/logout")
    assert login(client, "analyst", "old-password").status_code == 401
    assert login(client, "analyst", "new-password").status_code == 403

    analyst.status = UserStatus.ACTIVE.value
    db_session.commit()
    assert login(client, "analyst", "new-password").status_code == 200

    actions = {row.action for row in db_session.query(AuditLog).all()}
    assert {"user.role_change", "user.block", "user.password_reset"}.issubset(actions)

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
    assert db_session.query(AuditLog).filter_by(action="user.created").count() == 1


def test_non_admin_cannot_manage_users(client, db_session):
    analyst = create_user(db_session, "analyst", "secret")
    assert login(client, "analyst", "secret").status_code == 200

    response = client.get("/admin/users")

    assert response.status_code == 403
    assert client.delete(f"/admin/users/{analyst.id}").status_code == 403


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
    assert {"user.role_changed", "user.status_changed", "user.password_reset"}.issubset(actions)


def test_admin_can_delete_user_and_deleted_user_cannot_login_or_appear_in_list(client, db_session):
    create_user(db_session, "admin", "secret", Role.ADMIN)
    analyst = create_user(db_session, "analyst", "initial-password")
    assert login(client, "admin", "secret").status_code == 200

    response = client.delete(f"/admin/users/{analyst.id}")

    assert response.status_code == 204
    db_session.refresh(analyst)
    assert analyst.status == UserStatus.DELETED.value
    assert db_session.query(AuditLog).filter_by(action="user.deleted", entity_id=analyst.id).count() == 1

    list_response = client.get("/admin/users")
    assert list_response.status_code == 200
    assert {user["login"] for user in list_response.json()["users"]} == {"admin"}

    client.post("/auth/logout")
    assert login(client, "analyst", "initial-password").status_code == 403


def test_admin_cannot_delete_self(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    assert login(client, "admin", "secret").status_code == 200

    response = client.delete(f"/admin/users/{admin.id}")

    assert response.status_code == 409
    db_session.refresh(admin)
    assert admin.status == UserStatus.ACTIVE.value

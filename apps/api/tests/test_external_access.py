from types import SimpleNamespace
from uuid import uuid4

from app.dependencies import auth as auth_dependencies
from app.models.user import User
from app.schemas.enums import Role, UserStatus
from app.security.passwords import hash_password


def _user(db_session, login: str, role: Role) -> None:
    db_session.add(User(
        login=login,
        display_name=login,
        password_hash=hash_password("test-password"),
        role=role.value,
        status=UserStatus.ACTIVE.value,
    ))
    db_session.commit()


def test_private_mode_blocks_users_and_public_links_but_keeps_admin_access(client, db_session, monkeypatch):
    monkeypatch.setattr(
        auth_dependencies,
        "get_settings",
        lambda: SimpleNamespace(external_access_disabled=True),
    )
    _user(db_session, "regular", Role.USER)
    _user(db_session, "manager", Role.SUPERUSER)
    _user(db_session, "admin", Role.ADMIN)

    assert client.get("/health").status_code == 200
    assert client.get("/documents").status_code == 401
    assert client.get(f"/public/analyses/{uuid4()}").status_code == 401

    for login in ("regular", "manager"):
        assert client.post("/auth/login", json={"login": login, "password": "test-password"}).status_code == 200
        assert client.get("/auth/me").status_code == 200
        assert client.get("/documents").status_code == 403
        assert client.post("/documents").status_code == 403
        assert client.get(f"/public/analyses/{uuid4()}").status_code == 403
        client.post("/auth/logout")

    assert client.post("/auth/login", json={"login": "admin", "password": "test-password"}).status_code == 200
    assert client.get("/documents").status_code == 200
    assert client.get("/admin/users").status_code == 200
    assert client.get(f"/public/analyses/{uuid4()}").status_code == 404


def test_normal_mode_keeps_user_document_access(client, db_session, monkeypatch):
    monkeypatch.setattr(
        auth_dependencies,
        "get_settings",
        lambda: SimpleNamespace(external_access_disabled=False),
    )
    _user(db_session, "regular", Role.USER)
    client.post("/auth/login", json={"login": "regular", "password": "test-password"})
    assert client.get("/documents").status_code == 200

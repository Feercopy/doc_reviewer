from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.enums import Role, UserStatus
from app.security.passwords import hash_password, verify_password


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


def test_password_hash_verifies_and_does_not_contain_plaintext():
    password_hash = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("wrong password", password_hash)
    assert "correct horse battery staple" not in password_hash


def test_login_sets_http_only_cookie_and_me_returns_user(client, db_session):
    create_user(db_session, "admin", "secret", Role.ADMIN)

    response = client.post("/auth/login", json={"login": "admin", "password": "secret"})

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"
    assert "password" not in response.text
    assert "httponly" in response.headers["set-cookie"].lower()

    me = client.get("/auth/me")

    assert me.status_code == 200
    assert me.json()["login"] == "admin"


def test_login_rejects_wrong_password(client, db_session):
    create_user(db_session, "analyst", "secret")

    response = client.post("/auth/login", json={"login": "analyst", "password": "bad"})

    assert response.status_code == 401


def test_blocked_user_cannot_login_or_use_existing_session(client, db_session):
    user = create_user(db_session, "blocked", "secret", status=UserStatus.ACTIVE)
    assert client.post("/auth/login", json={"login": "blocked", "password": "secret"}).status_code == 200

    user.status = UserStatus.BLOCKED.value
    db_session.commit()

    assert client.get("/auth/me").status_code == 403
    client.post("/auth/logout")
    assert client.post("/auth/login", json={"login": "blocked", "password": "secret"}).status_code == 403


def test_logout_clears_session_cookie(client, db_session):
    create_user(db_session, "admin", "secret", Role.ADMIN)
    client.post("/auth/login", json={"login": "admin", "password": "secret"})

    response = client.post("/auth/logout")

    assert response.status_code == 200
    assert client.get("/auth/me").status_code == 401

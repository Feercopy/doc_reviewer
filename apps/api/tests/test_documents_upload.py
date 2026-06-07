from pathlib import Path
from uuid import UUID
import hashlib

import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import app
from app.models.document import Document
from app.routers import documents as documents_router
from app.models.user import User
from app.schemas.enums import Role, UserStatus
from app.security.passwords import hash_password


@pytest.fixture()
def storage_root(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture()
def enqueued_parse_jobs():
    enqueued: list[str] = []

    def fake_enqueue(document_id):
        enqueued.append(str(document_id))

    app.dependency_overrides[documents_router.get_parse_document_enqueue] = lambda: fake_enqueue
    yield enqueued
    app.dependency_overrides.pop(documents_router.get_parse_document_enqueue, None)


@pytest.fixture()
def api_client(storage_root, client, enqueued_parse_jobs):
    return client


def create_user(
    db_session: Session,
    login: str,
    password: str,
    role: Role = Role.USER,
) -> User:
    user = User(
        login=login,
        display_name=login.title(),
        password_hash=hash_password(password),
        role=role.value,
        status=UserStatus.ACTIVE.value,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def login(client, login: str, password: str) -> None:
    response = client.post("/auth/login", json={"login": login, "password": password})
    assert response.status_code == 200


def upload_document(client, filename: str, content: bytes, content_type: str = "text/plain"):
    return client.post(
        "/documents",
        data={"title": "Investment Defense"},
        files={"file": (filename, content, content_type)},
    )


def assert_under_storage_root(path: str, storage_root: Path) -> Path:
    storage_path = Path(path)
    assert storage_path.resolve().is_relative_to(storage_root.resolve())
    return storage_path


def test_upload_supported_file_creates_queued_document_and_raw_file(api_client, db_session, storage_root):
    content = b"# Gate 2\n\nMVP scope, traction, metrics, risks, and business case."
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")

    response = api_client.post(
        "/documents",
        data={"title": "Gate 2 Defense"},
        files={"file": ("gate-2.md", content, "text/markdown")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Gate 2 Defense"
    assert payload["original_filename"] == "gate-2.md"
    assert payload["parse_status"] == "queued"
    assert payload["detected_document_type"] == "unknown"
    assert payload["file_size_bytes"] == len(content)
    assert payload["file_hash_sha256"] == hashlib.sha256(content).hexdigest()
    assert "storage_path" not in payload

    document = db_session.query(Document).one()
    stored_path = assert_under_storage_root(document.storage_path, storage_root)
    assert stored_path.read_bytes() == content
    assert stored_path.name == f"{hashlib.sha256(content).hexdigest()}-gate-2.md"


def test_upload_enqueues_parse_job(api_client, db_session, enqueued_parse_jobs):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")

    response = upload_document(api_client, "gate-2.txt", b"Gate 2 MVP metrics")

    assert response.status_code == 201
    assert enqueued_parse_jobs == [response.json()["id"]]


def test_rejects_unsupported_file_with_415(api_client, db_session, storage_root):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")

    response = upload_document(
        api_client,
        "spreadsheet.xlsx",
        b"not supported",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert response.status_code == 415
    assert db_session.query(Document).count() == 0
    assert list(storage_root.rglob("*")) == []


def test_path_traversal_filename_is_sanitized_for_storage(api_client, db_session, storage_root):
    content = b"plain text defense"
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")

    response = upload_document(api_client, "../../secret.txt", content)

    assert response.status_code == 201
    document = db_session.query(Document).one()
    stored_path = assert_under_storage_root(document.storage_path, storage_root)
    assert stored_path.name == f"{hashlib.sha256(content).hexdigest()}-secret.txt"
    assert ".." not in stored_path.name
    assert "/" not in stored_path.name


def test_user_sees_only_own_documents_and_admin_sees_all(api_client, db_session):
    create_user(db_session, "admin", "secret", Role.ADMIN)
    create_user(db_session, "alice", "secret")
    create_user(db_session, "bob", "secret")

    login(api_client, "alice", "secret")
    alice_upload = upload_document(api_client, "alice.txt", b"alice document")
    assert alice_upload.status_code == 201
    api_client.post("/auth/logout")

    login(api_client, "bob", "secret")
    bob_upload = upload_document(api_client, "bob.txt", b"bob document")
    assert bob_upload.status_code == 201

    bob_documents = api_client.get("/documents")
    assert bob_documents.status_code == 200
    assert [document["original_filename"] for document in bob_documents.json()["documents"]] == ["bob.txt"]
    api_client.post("/auth/logout")

    login(api_client, "admin", "secret")
    admin_documents = api_client.get("/documents")
    assert admin_documents.status_code == 200
    assert {document["original_filename"] for document in admin_documents.json()["documents"]} == {
        "alice.txt",
        "bob.txt",
    }


def test_user_cannot_get_another_users_document_detail_but_admin_can(api_client, db_session):
    create_user(db_session, "admin", "secret", Role.ADMIN)
    create_user(db_session, "alice", "secret")
    create_user(db_session, "bob", "secret")

    login(api_client, "alice", "secret")
    alice_upload = upload_document(api_client, "alice.txt", b"alice document")
    assert alice_upload.status_code == 201
    alice_document_id = UUID(alice_upload.json()["id"])
    api_client.post("/auth/logout")

    login(api_client, "bob", "secret")
    forbidden_detail = api_client.get(f"/documents/{alice_document_id}")
    assert forbidden_detail.status_code == 404
    api_client.post("/auth/logout")

    login(api_client, "admin", "secret")
    admin_detail = api_client.get(f"/documents/{alice_document_id}")
    assert admin_detail.status_code == 200
    assert admin_detail.json()["original_filename"] == "alice.txt"


def test_rejects_oversized_upload_with_413(api_client, db_session):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")

    response = upload_document(api_client, "large.txt", b"x" * (25 * 1024 * 1024 + 1))

    assert response.status_code == 413
    assert db_session.query(Document).count() == 0

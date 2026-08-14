from pathlib import Path
from uuid import UUID
import io
import hashlib
import zipfile

import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import app
from app.models.analysis import Analysis, AnalysisCheckRun, PredictedCommentRun
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.models.skill import Skill
from app.routers import documents as documents_router
from app.models.user import User
from app.schemas.enums import DocumentParseStatus, DocumentRole, DocumentType, EntityStatus, Provider, Role, RunStatus, UserStatus
from app.security.passwords import hash_password
from app.security.secrets import encrypt_secret
from app.seeds.skills import seed_baseline_skills
from app.services.analyses import DOCUMENT_PARSE_DEPENDENCY_KEY


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


def valid_xlsx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("xl/workbook.xml", "<workbook/>")
    return buffer.getvalue()


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


def test_documents_api_reads_future_progress_review_rows(api_client, db_session):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")
    upload = upload_document(api_client, "progress.txt", b"Progress review")
    document = db_session.get(Document, UUID(upload.json()["id"]))
    document.detected_document_type = "progress_review"
    document.manual_document_type = "progress_review"
    db_session.commit()

    response = api_client.get(f"/documents/{document.id}")

    assert response.status_code == 200
    assert response.json()["detected_document_type"] == "progress_review"
    assert response.json()["manual_document_type"] == "progress_review"


def test_documents_api_accepts_activated_progress_review_writes(api_client, db_session):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")

    upload = api_client.post(
        "/documents",
        data={"title": "Progress", "manual_document_type": "progress_review"},
        files={"file": ("progress.txt", b"Progress review", "text/plain")},
    )

    assert upload.status_code == 201
    assert upload.json()["manual_document_type"] == "progress_review"
    regular_upload = upload_document(api_client, "regular.txt", b"Stream review")
    patch = api_client.patch(
        f"/documents/{regular_upload.json()['id']}/document-type",
        json={"manual_document_type": "progress_review"},
    )
    assert patch.status_code == 200
    assert patch.json()["manual_document_type"] == "progress_review"


def test_upload_persists_deferred_analysis_before_parser_runs(api_client, db_session, enqueued_parse_jobs):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    author = create_user(db_session, "author", "secret")
    seed_baseline_skills(db_session)
    main_skill = db_session.query(Skill).filter_by(name="gate2_challenger_main_analysis").one()
    main_skill.runtime_mode = "inline"
    main_skill.skill_source_id = None
    db_session.add(
        ProviderKey(
            owner_id=admin.id,
            provider=Provider.OPENAI_COMPATIBLE.value,
            default_model="openai/gpt-5.5",
            available_models=["openai/gpt-5.5"],
            encrypted_api_key=encrypt_secret("sk-test"),
            api_key_fingerprint="openai_compatible:...test",
        )
    )
    db_session.commit()
    login(api_client, author.login, "secret")

    response = api_client.post(
        "/documents",
        data={
            "title": "Gate 2 Defense",
            "analysis_provider": Provider.OPENAI_COMPATIBLE.value,
            "analysis_model": "openai/gpt-5.5",
            "analysis_output_language": "en",
        },
        files={"file": ("gate-2.md", b"# Gate 2\n\nMVP metrics", "text/markdown")},
    )

    assert response.status_code == 201
    document_id = UUID(response.json()["id"])
    analysis = db_session.query(Analysis).filter_by(document_id=document_id).one()
    assert analysis.user_id == author.id
    assert analysis.status == "queued"
    assert analysis.run_parameters["output_language"] == "en"
    assert analysis.run_parameters[DOCUMENT_PARSE_DEPENDENCY_KEY] == {
        "document_id": str(document_id),
        "state": "waiting",
    }
    assert enqueued_parse_jobs == [str(document_id)]


def test_documents_list_embeds_latest_analysis_status(api_client, db_session):
    author = create_user(db_session, "author", "secret")
    skill = seed_baseline_skills(db_session)[0]
    login(api_client, "author", "secret")
    upload = upload_document(api_client, "gate-2.txt", b"Gate 2 MVP metrics")
    document_id = UUID(upload.json()["id"])

    completed = Analysis(
        document_id=document_id,
        user_id=author.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="approve",
        summary="Older completed analysis",
        structured_output={"summary": "x" * 500_000},
        raw_output="raw secret output",
        run_parameters={},
    )
    db_session.add(completed)
    db_session.commit()

    queued = Analysis(
        document_id=document_id,
        user_id=author.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.QUEUED.value,
        verdict=None,
        summary=None,
        structured_output=None,
        raw_output="raw queued output" * 10_000,
        run_parameters={},
    )
    db_session.add(queued)
    db_session.flush()
    predicted = PredictedCommentRun(
        analysis_id=queued.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.RUNNING.value,
        structured_output={"secret": "y" * 500_000},
        raw_output="predicted secret" * 10_000,
        run_parameters={},
    )
    ic_review = AnalysisCheckRun(
        analysis_id=queued.id,
        skill_id=skill.id,
        skill_version=skill.version,
        check_type="ic_agentic_review",
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.QUEUED.value,
        current_stage="queued",
        structured_output={"secret": "z" * 500_000},
        raw_output="ic secret" * 10_000,
        run_parameters={},
        artifacts=[],
        uploaded_workbook_metadata={},
    )
    db_session.add_all([predicted, ic_review])
    db_session.commit()

    response = api_client.get("/documents")

    assert response.status_code == 200
    document = response.json()["documents"][0]
    assert document["id"] == str(document_id)
    assert document["latest_analysis"]["id"] == str(queued.id)
    assert document["latest_analysis"]["status"] == RunStatus.QUEUED.value
    assert document["latest_analysis"]["predicted_comment_run"]["status"] == RunStatus.RUNNING.value
    assert document["latest_analysis"]["ic_review_run"]["status"] == RunStatus.QUEUED.value
    assert "structured_output" not in document["latest_analysis"]
    assert "raw_output" not in document["latest_analysis"]
    assert "run_parameters" not in document["latest_analysis"]
    assert len(response.content) < 20_000


def test_upload_rejects_partial_analysis_config_before_storing_document(api_client, db_session, storage_root):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")

    response = api_client.post(
        "/documents",
        data={"analysis_provider": Provider.OPENAI_COMPATIBLE.value},
        files={"file": ("gate-2.md", b"# Gate 2", "text/markdown")},
    )

    assert response.status_code == 422
    assert db_session.query(Document).count() == 0
    assert not any(path.is_file() for path in storage_root.rglob("*"))


def test_upload_rejects_unsupported_primary_file_without_db_or_storage_artifacts(
    api_client,
    db_session,
    storage_root,
    enqueued_parse_jobs,
):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")

    response = upload_document(
        api_client,
        "spreadsheet.xlsx",
        valid_xlsx_bytes(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert response.status_code == 415
    assert db_session.query(Document).count() == 0
    assert enqueued_parse_jobs == []
    assert not any(path.is_file() for path in storage_root.rglob("*"))


def test_upload_can_attach_fin_summary_document_to_primary_document(api_client, db_session, enqueued_parse_jobs):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")

    response = api_client.post(
        "/documents",
        data={"title": "Gate 2 Defense"},
        files={
            "file": ("gate-2.docx", b"main defense", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            "fin_summary_file": (
                "fin-summary.xlsx",
                valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Gate 2 Defense"
    assert payload["document_role"] == "primary"
    assert payload["linked_fin_summary_document_id"] is not None
    assert payload["linked_fin_summary_document"]["original_filename"] == "fin-summary.xlsx"

    primary = db_session.get(Document, UUID(payload["id"]))
    fin_summary = db_session.get(Document, UUID(payload["linked_fin_summary_document_id"]))
    assert primary.document_role == DocumentRole.PRIMARY.value
    assert fin_summary.document_role == DocumentRole.FIN_SUMMARY.value
    assert primary.parse_status == DocumentParseStatus.QUEUED.value
    assert fin_summary.parse_status == DocumentParseStatus.COMPLETED.value
    assert fin_summary.parse_error is None
    assert primary.linked_fin_summary_document_id == fin_summary.id
    assert enqueued_parse_jobs == [str(primary.id)]

    documents_response = api_client.get("/documents")
    assert documents_response.status_code == 200
    documents = documents_response.json()["documents"]
    assert [document["original_filename"] for document in documents] == ["gate-2.docx"]
    assert documents[0]["linked_fin_summary_document"]["original_filename"] == "fin-summary.xlsx"
    assert documents[0]["linked_fin_summary_document"]["parse_status"] == DocumentParseStatus.COMPLETED.value


def test_upload_rejects_invalid_fin_summary_without_primary_or_storage_artifacts(
    api_client,
    db_session,
    storage_root,
    enqueued_parse_jobs,
):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")

    response = api_client.post(
        "/documents",
        data={"title": "Gate 2 Defense"},
        files={
            "file": ("gate-2.docx", b"main defense", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            "fin_summary_file": (
                "fin-summary.xlsx",
                b"not a zip workbook",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )

    assert response.status_code == 415
    assert db_session.query(Document).count() == 0
    assert enqueued_parse_jobs == []
    assert not any(path.is_file() for path in storage_root.rglob("*"))


def test_upload_cleans_primary_and_fin_summary_when_primary_enqueue_fails(
    client,
    db_session,
    storage_root,
):
    enqueued: list[str] = []

    def flaky_enqueue(document_id):
        enqueued.append(str(document_id))
        raise RuntimeError("redis unavailable")

    app.dependency_overrides[documents_router.get_parse_document_enqueue] = lambda: flaky_enqueue
    try:
        create_user(db_session, "author", "secret")
        login(client, "author", "secret")

        response = client.post(
            "/documents",
            data={"title": "Gate 2 Defense"},
            files={
                "file": ("gate-2.docx", b"main defense", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                "fin_summary_file": (
                    "fin-summary.xlsx",
                    valid_xlsx_bytes(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            },
        )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to enqueue document parsing"
        assert len(enqueued) == 1
        assert db_session.query(Document).count() == 0
        assert db_session.query(AuditLog).count() == 0
        assert not any(path.is_file() for path in storage_root.rglob("*"))
    finally:
        app.dependency_overrides.pop(documents_router.get_parse_document_enqueue, None)


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


def test_owner_can_delete_document_and_it_disappears_from_document_workflow(api_client, db_session):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")
    upload = upload_document(api_client, "gate.txt", b"Gate 2 MVP metrics")
    document_id = UUID(upload.json()["id"])

    response = api_client.delete(f"/documents/{document_id}")

    assert response.status_code == 204
    document = db_session.get(Document, document_id)
    assert document.status == EntityStatus.DELETED.value
    assert api_client.get("/documents").json()["documents"] == []
    assert api_client.get(f"/documents/{document_id}").status_code == 404
    assert db_session.query(AuditLog).filter_by(action="document.deleted", entity_id=document_id).count() == 1


def test_user_cannot_delete_another_users_document_but_admin_can(api_client, db_session):
    create_user(db_session, "admin", "secret", Role.ADMIN)
    create_user(db_session, "alice", "secret")
    create_user(db_session, "bob", "secret")

    login(api_client, "alice", "secret")
    upload = upload_document(api_client, "alice.txt", b"alice document")
    document_id = UUID(upload.json()["id"])
    api_client.post("/auth/logout")

    login(api_client, "bob", "secret")
    forbidden = api_client.delete(f"/documents/{document_id}")
    assert forbidden.status_code == 404
    assert db_session.get(Document, document_id).status == EntityStatus.ACTIVE.value
    api_client.post("/auth/logout")

    login(api_client, "admin", "secret")
    deleted = api_client.delete(f"/documents/{document_id}")

    assert deleted.status_code == 204
    assert db_session.get(Document, document_id).status == EntityStatus.DELETED.value


def test_manual_document_type_override_is_saved_separately(api_client, db_session):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")
    upload = upload_document(api_client, "gate.txt", b"Gate 2 MVP metrics")
    document_id = UUID(upload.json()["id"])

    response = api_client.patch(f"/documents/{document_id}/document-type", json={"manual_document_type": "stream_review_1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["manual_document_type"] == "stream_review_1"
    assert payload["detected_document_type"] == "unknown"
    document = db_session.get(Document, document_id)
    assert document.manual_document_type == DocumentType.STREAM_REVIEW_1.value


def test_owner_can_update_document_title(api_client, db_session):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")
    upload = upload_document(api_client, "gate.txt", b"Gate 2 MVP metrics")
    document_id = UUID(upload.json()["id"])

    response = api_client.patch(f"/documents/{document_id}/title", json={"title": "  TRX_SE revised  "})

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "TRX_SE revised"
    document = db_session.get(Document, document_id)
    assert document.title == "TRX_SE revised"
    audit = db_session.query(AuditLog).filter_by(action="document.title_updated", entity_id=document_id).one()
    assert audit.metadata_["from"] == "Investment Defense"
    assert audit.metadata_["to"] == "TRX_SE revised"


def test_rejects_empty_document_title_update(api_client, db_session):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")
    upload = upload_document(api_client, "gate.txt", b"Gate 2 MVP metrics")
    document_id = UUID(upload.json()["id"])

    response = api_client.patch(f"/documents/{document_id}/title", json={"title": "   "})

    assert response.status_code == 422
    assert db_session.get(Document, document_id).title == "Investment Defense"


def test_rejects_gate_1_manual_document_type(api_client, db_session):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")
    upload = upload_document(api_client, "gate.txt", b"Gate 2 MVP metrics")
    document_id = UUID(upload.json()["id"])

    response = api_client.patch(f"/documents/{document_id}/document-type", json={"manual_document_type": "gate_1"})

    assert response.status_code == 422


def test_get_parsed_text_requires_owner_and_completed_parse(api_client, db_session):
    create_user(db_session, "alice", "secret")
    create_user(db_session, "bob", "secret")
    login(api_client, "alice", "secret")
    upload = upload_document(api_client, "gate.txt", b"Gate 2 MVP metrics")
    document_id = UUID(upload.json()["id"])
    document = db_session.get(Document, document_id)
    document.parse_status = DocumentParseStatus.COMPLETED.value
    document.parsed_text = "Parsed Gate 2 text"
    db_session.commit()

    response = api_client.get(f"/documents/{document_id}/parsed-text")
    assert response.status_code == 200
    assert response.text == "Parsed Gate 2 text"
    assert response.headers["content-type"].startswith("text/plain")

    api_client.post("/auth/logout")
    login(api_client, "bob", "secret")
    forbidden = api_client.get(f"/documents/{document_id}/parsed-text")
    assert forbidden.status_code == 404


def test_get_parsed_text_returns_409_before_completed_parse(api_client, db_session):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")
    upload = upload_document(api_client, "gate.txt", b"Gate 2 MVP metrics")

    response = api_client.get(f"/documents/{upload.json()['id']}/parsed-text")

    assert response.status_code == 409


def test_get_raw_download_requires_owner_and_preserves_content(api_client, db_session):
    create_user(db_session, "alice", "secret")
    create_user(db_session, "bob", "secret")
    content = b"raw Gate 2 defense"
    login(api_client, "alice", "secret")
    upload = upload_document(api_client, "gate.txt", content)
    document_id = UUID(upload.json()["id"])

    response = api_client.get(f"/documents/{document_id}/raw")
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-disposition"].endswith('filename="gate.txt"')

    api_client.post("/auth/logout")
    login(api_client, "bob", "secret")
    forbidden = api_client.get(f"/documents/{document_id}/raw")
    assert forbidden.status_code == 404


def test_get_raw_download_rejects_storage_path_outside_storage_root(api_client, db_session, tmp_path):
    create_user(db_session, "alice", "secret")
    login(api_client, "alice", "secret")
    upload = upload_document(api_client, "gate.txt", b"raw Gate 2 defense")
    document_id = UUID(upload.json()["id"])
    document = db_session.get(Document, document_id)
    outside_path = tmp_path.parent / "outside-storage.txt"
    outside_path.write_bytes(b"must not be served")
    document.storage_path = str(outside_path)
    db_session.commit()

    response = api_client.get(f"/documents/{document_id}/raw")

    assert response.status_code == 404
    assert response.json()["detail"] == "Document file not found"


def test_reparse_resets_parse_state_and_enqueues_job(api_client, db_session, enqueued_parse_jobs):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")
    upload = upload_document(api_client, "gate.txt", b"Gate 2 MVP metrics")
    document_id = UUID(upload.json()["id"])
    enqueued_parse_jobs.clear()
    document = db_session.get(Document, document_id)
    document.parse_status = DocumentParseStatus.COMPLETED.value
    document.parsed_text = "old parsed text"
    document.parse_error = None
    document.detected_document_type = DocumentType.GATE_2.value
    document.document_type_confidence = "0.90"
    document.document_type_explanation = "old"
    db_session.commit()

    response = api_client.post(f"/documents/{document_id}/reparse")

    assert response.status_code == 200
    payload = response.json()
    assert payload["parse_status"] == "queued"
    assert payload["detected_document_type"] == "unknown"
    assert enqueued_parse_jobs == [str(document_id)]
    db_session.refresh(document)
    assert document.parsed_text is None
    assert document.parse_error is None


def test_reparse_rejects_fin_summary_without_enqueuing_generic_parser(api_client, db_session, enqueued_parse_jobs):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")
    upload = api_client.post(
        "/documents",
        files={
            "file": ("gate-2.docx", b"main defense", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            "fin_summary_file": (
                "fin-summary.xlsx",
                valid_xlsx_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )
    assert upload.status_code == 201
    fin_summary_id = UUID(upload.json()["linked_fin_summary_document_id"])
    enqueued_parse_jobs.clear()

    response = api_client.post(f"/documents/{fin_summary_id}/reparse")

    assert response.status_code == 409
    assert response.json()["detail"] == "Fin Summary workbooks do not use document parsing"
    assert enqueued_parse_jobs == []
    fin_summary = db_session.get(Document, fin_summary_id)
    assert fin_summary.parse_status == DocumentParseStatus.COMPLETED.value
    assert fin_summary.parse_error is None


def test_rejects_oversized_upload_with_413(api_client, db_session):
    create_user(db_session, "author", "secret")
    login(api_client, "author", "secret")

    response = upload_document(api_client, "large.txt", b"x" * (25 * 1024 * 1024 + 1))

    assert response.status_code == 413
    assert db_session.query(Document).count() == 0

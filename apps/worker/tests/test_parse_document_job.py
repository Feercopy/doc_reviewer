from io import BytesIO
from pathlib import Path
from uuid import uuid4
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.core.config import get_settings
from app.models.analysis import Analysis
from app.models.document import Document
from app.models.skill import Skill
from app.models.user import User
from app.schemas.enums import DocumentParseStatus, DocumentType, EntityStatus, Role, RunStatus, SkillType, UserStatus
from app.services.analyses import DOCUMENT_PARSE_DEPENDENCY_KEY
from app.security.passwords import hash_password
from app.storage.local import LocalDocumentStorage
from jobs.parse_document import _format_parse_error, parse_document
from parsers.anonymizer import PiiResidueError


def test_parse_document_success_updates_database_and_writes_artifact(tmp_path):
    db = _create_session()
    try:
        owner = _create_user(db)
        storage = LocalDocumentStorage(tmp_path)
        document = _create_document(
            db,
            storage,
            owner,
            filename="gate-2.md",
            content=b"# Gate 2\n\nMVP scope, traction, metrics, risks, and business case.",
            mime_type="text/markdown",
        )

        parse_document(str(document.id), db=db, storage=storage)

        db.refresh(document)
        assert document.parse_status == DocumentParseStatus.COMPLETED.value
        assert document.parsed_text is not None
        assert "MVP scope" in document.parsed_text
        assert document.detected_document_type == DocumentType.GATE_2.value
        assert document.document_type_confidence is not None
        assert document.document_type_confidence >= 0.45
        assert document.document_type_explanation is not None
        assert "Gate 2" in document.document_type_explanation
        assert document.parse_error is None

        parsed_artifact_path = tmp_path / "documents" / str(owner.id) / str(document.id) / "parsed" / "parsed.txt"
        assert parsed_artifact_path.read_text(encoding="utf-8") == document.parsed_text
        parsed_dir = parsed_artifact_path.parent
        assert (parsed_dir / "parsed.md").read_text(encoding="utf-8") == document.parsed_text
        structured = json.loads((parsed_dir / "structured.json").read_text(encoding="utf-8"))
        assert structured["schema_version"] == "document_parse_artifact.v1"
        assert structured["source"]["filename"] == "gate-2.md"
        assert structured["source"]["sha256"] == document.file_hash_sha256
        assert structured["parser"]["name"] == "utf8_text"
        assert structured["outputs"]["plain_text"] == document.parsed_text
        assert structured["blocks"][0]["type"] == "heading"
        quality = json.loads((parsed_dir / "quality.json").read_text(encoding="utf-8"))
        assert quality["block_count"] == 2
    finally:
        _close_session(db)


def test_parse_document_anonymizes_personal_data_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENT_ANONYMIZATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _create_session()
    try:
        owner = _create_user(db)
        storage = LocalDocumentStorage(tmp_path)
        document = _create_document(
            db,
            storage,
            owner,
            filename="ivan-petrov-gate-2.md",
            content=(
                "# Gate 2\n\n"
                "Иван Петров owns MVP scope, traction, metrics, risks, and business case.\n"
                "Contact ivan.petrov@example.com or +7 999 123-45-67."
            ).encode("utf-8"),
            mime_type="text/markdown",
        )
        document.title = "Иван Петров Gate 2"
        db.commit()

        parse_document(str(document.id), db=db, storage=storage)

        db.refresh(document)
        assert document.parse_status == DocumentParseStatus.COMPLETED.value
        assert document.detected_document_type == DocumentType.GATE_2.value
        assert document.parsed_text is not None
        assert "Иван" not in document.parsed_text
        assert "Петров" not in document.parsed_text
        assert "ivan.petrov@example.com" not in document.parsed_text
        assert "+7 999 123-45-67" not in document.parsed_text
        assert "Иван" not in document.title
        assert "Петров" not in document.title
        assert "[PERSON_001]" in document.title
        assert document.original_filename == "anonymized-document.md"
        assert "[PERSON_001]" in document.parsed_text
        assert "[EMAIL_001]" in document.parsed_text
        assert "[PHONE_001]" in document.parsed_text

        parsed_dir = tmp_path / "documents" / str(owner.id) / str(document.id) / "parsed"
        assert (parsed_dir / "parsed.txt").read_text(encoding="utf-8") == document.parsed_text
        structured = json.loads((parsed_dir / "structured.json").read_text(encoding="utf-8"))
        assert structured["source"]["filename"] == "anonymized-document.md"
        assert structured["outputs"]["plain_text"] == document.parsed_text
        assert structured["anonymization"]["enabled"] is True
        assert "Иван" not in json.dumps(structured, ensure_ascii=False)
        assert "Петров" not in json.dumps(structured, ensure_ascii=False)
    finally:
        _close_session(db)
        monkeypatch.delenv("DOCUMENT_ANONYMIZATION_ENABLED", raising=False)
        get_settings.cache_clear()


def test_parse_document_formats_pii_residue_errors_for_users():
    error = _format_parse_error(PiiResidueError({"email": 1, "phone": 2}))

    assert error == "PiiResidueError: personal_data_residue_detected residuals={'email': 1, 'phone': 2}"


def test_parse_document_failure_marks_failed_and_preserves_raw_file(tmp_path):
    db = _create_session()
    try:
        owner = _create_user(db)
        storage = LocalDocumentStorage(tmp_path)
        document = _create_document(
            db,
            storage,
            owner,
            filename="broken.pdf",
            content=b"not a valid pdf",
            mime_type="application/pdf",
        )
        raw_path = Path(document.storage_path)

        parse_document(str(document.id), db=db, storage=storage)

        db.refresh(document)
        assert document.parse_status == DocumentParseStatus.FAILED.value
        assert document.parsed_text is None
        assert document.parse_error
        assert raw_path.exists()
        assert raw_path.read_bytes() == b"not a valid pdf"
    finally:
        _close_session(db)


def test_parse_document_enqueues_persisted_analysis_after_parse(tmp_path):
    db = _create_session()
    try:
        owner = _create_user(db)
        storage = LocalDocumentStorage(tmp_path)
        document = _create_document(
            db,
            storage,
            owner,
            filename="gate-2.md",
            content=b"# Gate 2\n\nMVP scope, traction, metrics, risks, and business case.",
            mime_type="text/markdown",
        )
        skill = Skill(
            name="gate2_challenger_main_analysis",
            description="Gate Challenger",
            version="test",
            skill_type=SkillType.MAIN_ANALYSIS.value,
            supported_document_types=[DocumentType.GATE_2.value],
            source_type="inline_prompt",
            prompt_text="Review",
            result_schema_path="contracts/schemas/main-analysis-result.schema.json",
            runtime_mode="inline",
            status=EntityStatus.ACTIVE.value,
        )
        db.add(skill)
        db.flush()
        analysis = Analysis(
            document_id=document.id,
            user_id=owner.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider="openai_compatible",
            model="openai/gpt-5.5",
            status=RunStatus.QUEUED.value,
            run_parameters={
                "document_type": DocumentType.UNKNOWN.value,
                DOCUMENT_PARSE_DEPENDENCY_KEY: {
                    "document_id": str(document.id),
                    "state": "waiting",
                },
            },
        )
        db.add(analysis)
        db.commit()
        enqueued: list[str] = []

        parse_document(
            str(document.id),
            db=db,
            storage=storage,
            enqueue_analysis=lambda analysis_id: enqueued.append(str(analysis_id)),
        )

        db.refresh(analysis)
        assert enqueued == [str(analysis.id)]
        assert analysis.status == RunStatus.QUEUED.value
        assert analysis.run_parameters["document_type"] == DocumentType.GATE_2.value
        assert analysis.run_parameters[DOCUMENT_PARSE_DEPENDENCY_KEY]["state"] == "enqueued"
    finally:
        _close_session(db)


def _create_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    session._test_engine = engine  # type: ignore[attr-defined]
    return session


def _close_session(session: Session) -> None:
    engine = session._test_engine  # type: ignore[attr-defined]
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _create_user(db: Session) -> User:
    user = User(
        login=f"owner-{uuid4()}",
        display_name="Owner",
        password_hash=hash_password("secret"),
        role=Role.USER.value,
        status=UserStatus.ACTIVE.value,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_document(
    db: Session,
    storage: LocalDocumentStorage,
    owner: User,
    *,
    filename: str,
    content: bytes,
    mime_type: str,
) -> Document:
    document_id = uuid4()
    stored_file = storage.save_raw_file(
        owner_id=owner.id,
        document_id=document_id,
        original_filename=filename,
        source=BytesIO(content),
        max_size_bytes=1024 * 1024,
    )
    document = Document(
        id=document_id,
        owner_id=owner.id,
        title="Investment Defense",
        original_filename=filename,
        mime_type=mime_type,
        file_size_bytes=stored_file.size_bytes,
        file_hash_sha256=stored_file.sha256,
        storage_path=str(stored_file.path),
        parse_status=DocumentParseStatus.QUEUED.value,
        detected_document_type=DocumentType.UNKNOWN.value,
        status=EntityStatus.ACTIVE.value,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document

from io import BytesIO
from pathlib import Path
from uuid import uuid4
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.document import Document
from app.models.user import User
from app.schemas.enums import DocumentParseStatus, DocumentType, EntityStatus, Role, UserStatus
from app.security.passwords import hash_password
from app.storage.local import LocalDocumentStorage
from jobs.parse_document import parse_document


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

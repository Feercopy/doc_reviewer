from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.document import Document
from app.schemas.enums import DocumentParseStatus
from app.services.document_type_detector import detect_document_type
from app.storage.local import LocalDocumentStorage
from parsers import parse_file


def parse_document(
    document_id: str,
    *,
    db: Session | None = None,
    storage: LocalDocumentStorage | None = None,
) -> None:
    owns_session = db is None
    session = db or SessionLocal()
    document_uuid = UUID(str(document_id))

    try:
        document = session.get(Document, document_uuid)
        if document is None:
            raise ValueError(f"Document {document_id} not found")

        document.parse_status = DocumentParseStatus.RUNNING.value
        document.parse_error = None
        session.commit()

        storage_service = storage or LocalDocumentStorage(get_settings().storage_root)
        raw_path = Path(document.storage_path)
        parsed_text = parse_file(raw_path)
        storage_service.save_parsed_artifact(
            owner_id=document.owner_id,
            document_id=document.id,
            parsed_text=parsed_text,
        )
        detection = detect_document_type(parsed_text)

        document.parsed_text = parsed_text
        document.detected_document_type = detection.document_type.value
        document.document_type_confidence = detection.confidence
        document.document_type_explanation = detection.explanation
        document.parse_status = DocumentParseStatus.COMPLETED.value
        document.parse_error = None
        session.commit()
    except Exception as exc:
        session.rollback()
        failed_document = session.get(Document, document_uuid)
        if failed_document is None:
            raise
        failed_document.parse_status = DocumentParseStatus.FAILED.value
        failed_document.parse_error = _format_parse_error(exc)
        session.commit()
    finally:
        if owns_session:
            session.close()


def _format_parse_error(error: Exception) -> str:
    return f"{error.__class__.__name__}: {error}"

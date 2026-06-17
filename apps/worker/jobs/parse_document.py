from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.document import Document
from app.logging import worker_logger
from app.schemas.enums import DocumentParseStatus
from app.services.audit import record_audit
from app.services.document_type_detector import detect_document_type
from app.storage.local import LocalDocumentStorage
from parsers import parse_file_to_document


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
        worker_logger.info(
            "worker_job_started",
            extra={"job_type": "parse_document", "entity_id": str(document_uuid), "status": "running"},
        )
        document = session.get(Document, document_uuid)
        if document is None:
            raise ValueError(f"Document {document_id} not found")

        document.parse_status = DocumentParseStatus.RUNNING.value
        document.parse_error = None
        session.commit()

        storage_service = storage or LocalDocumentStorage(get_settings().storage_root)
        raw_path = Path(document.storage_path)
        parsed_document = parse_file_to_document(raw_path)
        parsed_text = parsed_document.plain_text
        structured_artifact = parsed_document.to_artifact(
            source_filename=document.original_filename,
            source_mime_type=document.mime_type,
            source_sha256=document.file_hash_sha256,
            source_size_bytes=document.file_size_bytes,
        )
        parsed_artifacts = storage_service.save_parsed_artifacts(
            owner_id=document.owner_id,
            document_id=document.id,
            parsed_text=parsed_text,
            parsed_markdown=parsed_document.markdown,
            structured_artifact=structured_artifact,
            quality_report=parsed_document.quality.to_dict(),
        )
        detection = detect_document_type(parsed_text)

        document.parsed_text = parsed_text
        document.detected_document_type = detection.document_type.value
        document.document_type_confidence = detection.confidence
        document.document_type_explanation = detection.explanation
        document.parse_status = DocumentParseStatus.COMPLETED.value
        document.parse_error = None
        record_audit(
            db=session,
            actor_id=None,
            action="document.parsed",
            entity_type="document",
            entity_id=document.id,
            metadata={
                "owner_id": str(document.owner_id),
                "detected_document_type": document.detected_document_type,
                "document_type_confidence": str(document.document_type_confidence),
                "parser": parsed_document.parser.name,
                "parsed_artifacts": sorted(parsed_artifacts.keys()),
                "parse_quality": parsed_document.quality.to_dict(),
            },
        )
        session.commit()
        worker_logger.info(
            "worker_job_completed",
            extra={"job_type": "parse_document", "entity_id": str(document_uuid), "status": "completed"},
        )
    except Exception as exc:
        session.rollback()
        failed_document = session.get(Document, document_uuid)
        if failed_document is None:
            raise
        failed_document.parse_status = DocumentParseStatus.FAILED.value
        failed_document.parse_error = _format_parse_error(exc)
        record_audit(
            db=session,
            actor_id=None,
            action="document.parse_failed",
            entity_type="document",
            entity_id=failed_document.id,
            metadata={"owner_id": str(failed_document.owner_id), "error_class": exc.__class__.__name__},
        )
        session.commit()
        worker_logger.info(
            "worker_job_failed",
            extra={
                "job_type": "parse_document",
                "entity_id": str(document_uuid),
                "status": "failed",
                "error_class": exc.__class__.__name__,
            },
        )
    finally:
        if owns_session:
            session.close()


def _format_parse_error(error: Exception) -> str:
    return f"{error.__class__.__name__}: {error}"

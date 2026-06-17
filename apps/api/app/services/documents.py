from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authz.policies import can_read_document
from app.models.document import Document
from app.models.user import User
from app.schemas.enums import DocumentParseStatus, DocumentType, EntityStatus, Role
from app.services.audit import record_audit
from app.storage.local import LocalDocumentStorage, StoredFileTooLargeError, safe_filename


MAX_UPLOAD_SIZE_BYTES = 25 * 1024 * 1024
SUPPORTED_EXTENSIONS_TO_MIME_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".dotx": "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".txt": "text/plain",
}


class UnsupportedDocumentFileTypeError(ValueError):
    pass


class DocumentTooLargeError(ValueError):
    pass


class DocumentNotFoundError(ValueError):
    pass


def create_document_from_upload(
    *,
    db: Session,
    actor: User,
    storage: LocalDocumentStorage,
    upload: UploadFile,
    title: str | None,
    manual_document_type: DocumentType | None,
) -> Document:
    original_filename = upload.filename or "upload"
    extension = _supported_extension(original_filename)
    document_id = uuid4()

    try:
        stored_file = storage.save_raw_file(
            owner_id=actor.id,
            document_id=document_id,
            original_filename=original_filename,
            source=upload.file,
            max_size_bytes=MAX_UPLOAD_SIZE_BYTES,
        )
    except StoredFileTooLargeError as exc:
        raise DocumentTooLargeError("File exceeds maximum upload size") from exc

    document = Document(
        id=document_id,
        owner_id=actor.id,
        title=_normalize_title(title, original_filename),
        original_filename=original_filename,
        mime_type=upload.content_type or SUPPORTED_EXTENSIONS_TO_MIME_TYPES[extension],
        file_size_bytes=stored_file.size_bytes,
        file_hash_sha256=stored_file.sha256,
        storage_path=str(stored_file.path),
        parse_status=DocumentParseStatus.QUEUED.value,
        detected_document_type=DocumentType.UNKNOWN.value,
        manual_document_type=manual_document_type.value if manual_document_type else None,
        status=EntityStatus.ACTIVE.value,
    )
    db.add(document)
    record_audit(
        db=db,
        actor_id=actor.id,
        action="document.uploaded",
        entity_type="document",
        entity_id=document.id,
        metadata={
            "owner_id": str(actor.id),
            "original_filename": document.original_filename,
            "file_size_bytes": document.file_size_bytes,
            "file_hash_sha256": document.file_hash_sha256,
        },
    )
    db.commit()
    db.refresh(document)
    return document


def create_document_from_local_file(
    *,
    db: Session,
    actor: User,
    storage: LocalDocumentStorage,
    source_path: Path,
    title: str | None,
    manual_document_type: DocumentType | None,
) -> Document:
    source_path = Path(source_path)
    extension = _supported_extension(source_path.name)
    document_id = uuid4()
    with source_path.open("rb") as source:
        stored_file = _save_raw_file(
            storage=storage,
            owner_id=actor.id,
            document_id=document_id,
            original_filename=source_path.name,
            source=source,
        )

    document = Document(
        id=document_id,
        owner_id=actor.id,
        title=_normalize_title(title, source_path.name),
        original_filename=source_path.name,
        mime_type=SUPPORTED_EXTENSIONS_TO_MIME_TYPES[extension],
        file_size_bytes=stored_file.size_bytes,
        file_hash_sha256=stored_file.sha256,
        storage_path=str(stored_file.path),
        parse_status=DocumentParseStatus.QUEUED.value,
        detected_document_type=DocumentType.UNKNOWN.value,
        manual_document_type=manual_document_type.value if manual_document_type else None,
        status=EntityStatus.ACTIVE.value,
    )
    db.add(document)
    record_audit(
        db=db,
        actor_id=actor.id,
        action="document.imported",
        entity_type="document",
        entity_id=document.id,
        metadata={
            "owner_id": str(actor.id),
            "original_filename": document.original_filename,
            "file_size_bytes": document.file_size_bytes,
            "file_hash_sha256": document.file_hash_sha256,
        },
    )
    db.flush()
    return document


def list_documents_for_actor(*, db: Session, actor: User) -> list[Document]:
    statement = select(Document).where(Document.status == EntityStatus.ACTIVE.value)
    if actor.role != Role.ADMIN.value:
        statement = statement.where(Document.owner_id == actor.id)
    statement = statement.order_by(Document.created_at.desc())
    return list(db.execute(statement).scalars().all())


def get_document_for_actor(*, db: Session, actor: User, document_id: UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.status != EntityStatus.ACTIVE.value or not can_read_document(actor, document):
        raise DocumentNotFoundError("Document not found")
    return document


def update_manual_document_type(
    *,
    db: Session,
    actor: User,
    document_id: UUID,
    manual_document_type: DocumentType | None,
) -> Document:
    document = get_document_for_actor(db=db, actor=actor, document_id=document_id)
    previous = document.manual_document_type
    document.manual_document_type = manual_document_type.value if manual_document_type else None
    record_audit(
        db=db,
        actor_id=actor.id,
        action="document.type_overridden",
        entity_type="document",
        entity_id=document.id,
        metadata={"from": previous, "to": document.manual_document_type},
    )
    db.commit()
    db.refresh(document)
    return document


def update_document_title(*, db: Session, actor: User, document_id: UUID, title: str) -> Document:
    document = get_document_for_actor(db=db, actor=actor, document_id=document_id)
    previous = document.title
    document.title = title
    record_audit(
        db=db,
        actor_id=actor.id,
        action="document.title_updated",
        entity_type="document",
        entity_id=document.id,
        metadata={"from": previous, "to": document.title},
    )
    db.commit()
    db.refresh(document)
    return document


def delete_document_for_actor(*, db: Session, actor: User, document_id: UUID) -> None:
    document = get_document_for_actor(db=db, actor=actor, document_id=document_id)
    previous_status = document.status
    document.status = EntityStatus.DELETED.value
    record_audit(
        db=db,
        actor_id=actor.id,
        action="document.deleted",
        entity_type="document",
        entity_id=document.id,
        metadata={"status": {"from": previous_status, "to": document.status}},
    )
    db.commit()


def reset_document_for_reparse(*, db: Session, actor: User, document_id: UUID) -> Document:
    document = get_document_for_actor(db=db, actor=actor, document_id=document_id)
    document.parse_status = DocumentParseStatus.QUEUED.value
    document.detected_document_type = DocumentType.UNKNOWN.value
    document.document_type_confidence = None
    document.document_type_explanation = None
    document.parsed_text = None
    document.parse_error = None
    db.commit()
    db.refresh(document)
    return document


def _supported_extension(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS_TO_MIME_TYPES:
        raise UnsupportedDocumentFileTypeError("Unsupported document file type")
    return extension


def _save_raw_file(
    *,
    storage: LocalDocumentStorage,
    owner_id: UUID,
    document_id: UUID,
    original_filename: str,
    source: BinaryIO,
):
    try:
        return storage.save_raw_file(
            owner_id=owner_id,
            document_id=document_id,
            original_filename=original_filename,
            source=source,
            max_size_bytes=MAX_UPLOAD_SIZE_BYTES,
        )
    except StoredFileTooLargeError as exc:
        raise DocumentTooLargeError("File exceeds maximum upload size") from exc


def _normalize_title(title: str | None, original_filename: str) -> str:
    if title and title.strip():
        return title.strip()

    fallback = Path(safe_filename(original_filename)).stem.strip()
    return fallback or "Untitled document"

from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4
import zipfile

from fastapi import UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.authz.policies import can_read_document
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.user import User
from app.schemas.enums import DocumentParseStatus, DocumentRole, DocumentType, EntityStatus, Role
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
FIN_SUMMARY_EXTENSIONS_TO_MIME_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
DEFAULT_MIME_TYPE = "application/octet-stream"


class UnsupportedDocumentFileTypeError(ValueError):
    pass


class DocumentTooLargeError(ValueError):
    pass


class DocumentNotFoundError(ValueError):
    pass


class UploadedDocumentBundle:
    def __init__(self, primary_document: Document, enqueued_document_ids: list[UUID]) -> None:
        self.primary_document = primary_document
        self.enqueued_document_ids = enqueued_document_ids


def create_document_from_upload(
    *,
    db: Session,
    actor: User,
    storage: LocalDocumentStorage,
    upload: UploadFile,
    title: str | None,
    manual_document_type: DocumentType | None,
    document_role: DocumentRole = DocumentRole.PRIMARY,
) -> Document:
    original_filename = upload.filename or "upload"
    extension = _supported_extension(original_filename, document_role=document_role)
    if document_role == DocumentRole.FIN_SUMMARY:
        _validate_fin_summary_upload(upload)
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
        mime_type=upload.content_type or _mime_type_for_role(extension=extension, document_role=document_role),
        file_size_bytes=stored_file.size_bytes,
        file_hash_sha256=stored_file.sha256,
        storage_path=str(stored_file.path),
        parse_status=DocumentParseStatus.QUEUED.value,
        detected_document_type=DocumentType.UNKNOWN.value,
        manual_document_type=manual_document_type.value if manual_document_type else None,
        document_role=document_role.value,
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
            "document_role": document.document_role,
        },
    )
    db.commit()
    db.refresh(document)
    return document


def create_uploaded_document_bundle(
    *,
    db: Session,
    actor: User,
    storage: LocalDocumentStorage,
    primary_upload: UploadFile,
    fin_summary_upload: UploadFile | None,
    title: str | None,
    manual_document_type: DocumentType | None,
) -> UploadedDocumentBundle:
    primary_original_filename = primary_upload.filename or "upload"
    primary_extension = _supported_extension(primary_original_filename, document_role=DocumentRole.PRIMARY)
    fin_summary_original_filename = fin_summary_upload.filename if fin_summary_upload is not None else None
    fin_summary_extension = None
    if fin_summary_upload is not None and fin_summary_original_filename:
        fin_summary_extension = _supported_extension(
            fin_summary_original_filename,
            document_role=DocumentRole.FIN_SUMMARY,
        )
        _validate_fin_summary_upload(fin_summary_upload)
    else:
        fin_summary_upload = None

    stored_document_ids: list[UUID] = []
    try:
        primary_document_id = uuid4()
        primary_stored_file = _save_raw_file(
            storage=storage,
            owner_id=actor.id,
            document_id=primary_document_id,
            original_filename=primary_original_filename,
            source=primary_upload.file,
        )
        stored_document_ids.append(primary_document_id)

        fin_summary_document = None
        if fin_summary_upload is not None and fin_summary_original_filename and fin_summary_extension:
            fin_summary_document_id = uuid4()
            fin_summary_stored_file = _save_raw_file(
                storage=storage,
                owner_id=actor.id,
                document_id=fin_summary_document_id,
                original_filename=fin_summary_original_filename,
                source=fin_summary_upload.file,
            )
            stored_document_ids.append(fin_summary_document_id)
            fin_summary_document = _build_document(
                document_id=fin_summary_document_id,
                actor=actor,
                original_filename=fin_summary_original_filename,
                title=None,
                manual_document_type=None,
                document_role=DocumentRole.FIN_SUMMARY,
                extension=fin_summary_extension,
                stored_file=fin_summary_stored_file,
            )
            db.add(fin_summary_document)

        primary_document = _build_document(
            document_id=primary_document_id,
            actor=actor,
            original_filename=primary_original_filename,
            title=title,
            manual_document_type=manual_document_type,
            document_role=DocumentRole.PRIMARY,
            extension=primary_extension,
            stored_file=primary_stored_file,
        )
        if fin_summary_document is not None:
            primary_document.linked_fin_summary_document_id = fin_summary_document.id
        db.add(primary_document)
        _record_document_uploaded(db=db, actor=actor, document=primary_document)
        if fin_summary_document is not None:
            _record_document_uploaded(db=db, actor=actor, document=fin_summary_document)
            record_audit(
                db=db,
                actor_id=actor.id,
                action="document.fin_summary_attached",
                entity_type="document",
                entity_id=primary_document.id,
                metadata={
                    "owner_id": str(actor.id),
                    "fin_summary_document_id": str(fin_summary_document.id),
                    "fin_summary_original_filename": fin_summary_document.original_filename,
                },
            )
        db.commit()
        db.refresh(primary_document)
        return UploadedDocumentBundle(
            primary_document=primary_document,
            enqueued_document_ids=[primary_document.id],
        )
    except Exception:
        db.rollback()
        for document_id in stored_document_ids:
            storage.delete_document_dir(owner_id=actor.id, document_id=document_id)
        raise


def cleanup_uploaded_document_bundle(
    *,
    db: Session,
    storage: LocalDocumentStorage,
    primary_document_id: UUID,
) -> None:
    primary_document = db.get(Document, primary_document_id)
    if primary_document is None:
        return
    document_ids = [primary_document.id]
    if primary_document.linked_fin_summary_document_id is not None:
        document_ids.append(primary_document.linked_fin_summary_document_id)
    owner_id = primary_document.owner_id
    primary_document.linked_fin_summary_document_id = None
    db.flush()
    db.execute(delete(AuditLog).where(AuditLog.entity_type == "document", AuditLog.entity_id.in_(document_ids)))
    db.execute(delete(Document).where(Document.id == primary_document.id))
    if len(document_ids) > 1:
        db.execute(delete(Document).where(Document.id.in_(document_ids[1:])))
    db.commit()
    for document_id in document_ids:
        storage.delete_document_dir(owner_id=owner_id, document_id=document_id)


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
        mime_type=SUPPORTED_EXTENSIONS_TO_MIME_TYPES.get(extension, DEFAULT_MIME_TYPE),
        file_size_bytes=stored_file.size_bytes,
        file_hash_sha256=stored_file.sha256,
        storage_path=str(stored_file.path),
        parse_status=DocumentParseStatus.QUEUED.value,
        detected_document_type=DocumentType.UNKNOWN.value,
        manual_document_type=manual_document_type.value if manual_document_type else None,
        document_role=DocumentRole.PRIMARY.value,
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
    statement = (
        select(Document)
        .options(selectinload(Document.linked_fin_summary_document))
        .where(
            Document.status == EntityStatus.ACTIVE.value,
            Document.document_role == DocumentRole.PRIMARY.value,
        )
    )
    if actor.role != Role.ADMIN.value:
        statement = statement.where(Document.owner_id == actor.id)
    statement = statement.order_by(Document.created_at.desc())
    return list(db.execute(statement).scalars().all())


def get_document_for_actor(*, db: Session, actor: User, document_id: UUID) -> Document:
    document = db.execute(
        select(Document)
        .options(selectinload(Document.linked_fin_summary_document))
        .where(Document.id == document_id)
    ).scalar_one_or_none()
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
    linked_fin_summary_id = document.linked_fin_summary_document_id
    if linked_fin_summary_id is not None:
        linked_fin_summary = db.get(Document, linked_fin_summary_id)
        if linked_fin_summary is not None and linked_fin_summary.owner_id == document.owner_id:
            linked_fin_summary.status = EntityStatus.DELETED.value
    record_audit(
        db=db,
        actor_id=actor.id,
        action="document.deleted",
        entity_type="document",
        entity_id=document.id,
        metadata={
            "status": {"from": previous_status, "to": document.status},
            "linked_fin_summary_document_id": str(linked_fin_summary_id) if linked_fin_summary_id else None,
        },
    )
    db.commit()


def attach_fin_summary_document(
    *,
    db: Session,
    actor: User,
    primary_document: Document,
    fin_summary_document: Document,
) -> Document:
    if primary_document.owner_id != actor.id or fin_summary_document.owner_id != actor.id:
        raise DocumentNotFoundError("Document not found")
    primary_document.linked_fin_summary_document_id = fin_summary_document.id
    record_audit(
        db=db,
        actor_id=actor.id,
        action="document.fin_summary_attached",
        entity_type="document",
        entity_id=primary_document.id,
        metadata={
            "owner_id": str(actor.id),
            "fin_summary_document_id": str(fin_summary_document.id),
            "fin_summary_original_filename": fin_summary_document.original_filename,
        },
    )
    db.commit()
    db.refresh(primary_document)
    return primary_document


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


def _supported_extension(filename: str, *, document_role: DocumentRole = DocumentRole.PRIMARY) -> str:
    extension = Path(filename).suffix.lower()
    supported = FIN_SUMMARY_EXTENSIONS_TO_MIME_TYPES if document_role == DocumentRole.FIN_SUMMARY else SUPPORTED_EXTENSIONS_TO_MIME_TYPES
    if extension not in supported:
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


def _validate_fin_summary_upload(upload: UploadFile) -> None:
    try:
        upload.file.seek(0)
        with zipfile.ZipFile(upload.file) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError) as exc:
        raise UnsupportedDocumentFileTypeError("Unsupported document file type") from exc
    finally:
        upload.file.seek(0)

    if "[Content_Types].xml" not in names or not any(name.startswith("xl/") for name in names):
        raise UnsupportedDocumentFileTypeError("Unsupported document file type")


def _build_document(
    *,
    document_id: UUID,
    actor: User,
    original_filename: str,
    title: str | None,
    manual_document_type: DocumentType | None,
    document_role: DocumentRole,
    extension: str,
    stored_file,
) -> Document:
    parse_status = (
        DocumentParseStatus.COMPLETED.value
        if document_role == DocumentRole.FIN_SUMMARY
        else DocumentParseStatus.QUEUED.value
    )
    return Document(
        id=document_id,
        owner_id=actor.id,
        title=_normalize_title(title, original_filename),
        original_filename=original_filename,
        mime_type=_mime_type_for_role(extension=extension, document_role=document_role),
        file_size_bytes=stored_file.size_bytes,
        file_hash_sha256=stored_file.sha256,
        storage_path=str(stored_file.path),
        parse_status=parse_status,
        detected_document_type=DocumentType.UNKNOWN.value,
        manual_document_type=manual_document_type.value if manual_document_type else None,
        document_role=document_role.value,
        status=EntityStatus.ACTIVE.value,
    )


def _record_document_uploaded(*, db: Session, actor: User, document: Document) -> None:
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
            "document_role": document.document_role,
        },
    )


def _mime_type_for_role(*, extension: str, document_role: DocumentRole) -> str:
    mime_types = FIN_SUMMARY_EXTENSIONS_TO_MIME_TYPES if document_role == DocumentRole.FIN_SUMMARY else SUPPORTED_EXTENSIONS_TO_MIME_TYPES
    return mime_types.get(extension, DEFAULT_MIME_TYPE)

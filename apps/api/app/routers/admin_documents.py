from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_admin
from app.models.document import Document
from app.models.user import User
from app.schemas.admin import AdminDocumentRead, AdminDocumentsListResponse
from app.schemas.enums import DocumentType, EntityStatus
from app.services.audit import record_audit

router = APIRouter(prefix="/admin/documents", tags=["admin-documents"])


@router.get("", response_model=AdminDocumentsListResponse)
def list_admin_documents(
    owner_id: UUID | None = None,
    document_type: DocumentType | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminDocumentsListResponse:
    statement = (
        select(Document, User)
        .join(User, User.id == Document.owner_id)
        .where(Document.status != EntityStatus.DELETED.value)
    )
    if owner_id is not None:
        statement = statement.where(Document.owner_id == owner_id)
    if document_type is not None:
        statement = statement.where(
            (Document.manual_document_type == document_type.value)
            | ((Document.manual_document_type.is_(None)) & (Document.detected_document_type == document_type.value))
        )
    if created_from is not None:
        statement = statement.where(Document.created_at >= created_from)
    if created_to is not None:
        statement = statement.where(Document.created_at <= created_to)
    statement = statement.order_by(Document.created_at.desc())
    return AdminDocumentsListResponse(
        documents=[_read_document(document, owner) for document, owner in db.execute(statement).all()]
    )


@router.post("/{document_id}/archive", response_model=AdminDocumentRead)
def archive_admin_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminDocumentRead:
    row = db.execute(select(Document, User).join(User, User.id == Document.owner_id).where(Document.id == document_id)).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    document, owner = row
    document.status = EntityStatus.ARCHIVED.value
    record_audit(
        db=db,
        actor_id=admin.id,
        action="document.archived",
        entity_type="document",
        entity_id=document.id,
        metadata={"owner_id": str(document.owner_id), "title": document.title},
    )
    db.commit()
    db.refresh(document)
    return _read_document(document, owner)


def _read_document(document: Document, owner: User) -> AdminDocumentRead:
    return AdminDocumentRead(
        id=document.id,
        owner_id=document.owner_id,
        owner_login=owner.login,
        title=document.title,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        file_size_bytes=document.file_size_bytes,
        file_hash_sha256=document.file_hash_sha256,
        parse_status=document.parse_status,
        detected_document_type=document.detected_document_type,
        manual_document_type=document.manual_document_type,
        document_type_confidence=document.document_type_confidence,
        parse_error=document.parse_error,
        status=document.status,
        parsed_text_available=document.parsed_text is not None,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.authz.policies import can_read_document
from app.db.session import get_db
from app.dependencies.auth import require_admin
from app.models.analysis import Analysis
from app.models.document import Document
from app.models.user import User
from app.schemas.analyses import AnalysisStatusRead
from app.schemas.admin import AdminDocumentRead, AdminDocumentsListResponse
from app.schemas.documents import DocumentRead, DocumentsListResponse
from app.schemas.enums import DocumentType, EntityStatus
from app.services.analyses import (
    ANALYSIS_CHAIN_CANCEL_REQUESTED_AT_KEY,
    AnalysisStatusSource,
    latest_document_analysis_statuses_for_actor,
    read_analysis_statuses,
)
from app.services.audit import record_audit
from app.services.documents import DocumentNotFoundError, get_document_for_actor

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


@router.get("/recovered", response_model=DocumentsListResponse)
def list_recovered_admin_documents(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> DocumentsListResponse:
    latest_analysis_at = func.max(Analysis.created_at).label("latest_analysis_at")
    rows = db.execute(
        select(Document, latest_analysis_at)
        .join(Analysis, Analysis.document_id == Document.id)
        .options(selectinload(Document.linked_fin_summary_document))
        .where(
            Analysis.deleted_at.is_(None),
            Document.status == EntityStatus.ACTIVE.value,
        )
        .group_by(Document.id)
        .order_by(latest_analysis_at.desc())
    ).all()
    documents = [document for document, _ in rows if can_read_document(admin, document)]
    recovered_through_detail_lookup = False
    if not documents:
        documents = _recover_documents_through_detail_lookup(db=db, admin=admin)
        recovered_through_detail_lookup = True
    if recovered_through_detail_lookup:
        latest_analyses = _latest_analysis_statuses_through_analysis_lookup(
            db=db,
            document_ids=[document.id for document in documents],
        )
    else:
        latest_analyses = latest_document_analysis_statuses_for_actor(
            db=db,
            actor=admin,
            document_ids=[document.id for document in documents],
        )
    return DocumentsListResponse(
        documents=[
            DocumentRead.model_validate(document).model_copy(
                update={"latest_analysis": latest_analyses.get(document.id)}
            )
            for document in documents
        ]
    )


def _recover_documents_through_detail_lookup(*, db: Session, admin: User) -> list[Document]:
    rows = db.execute(
        select(Analysis.document_id)
        .where(Analysis.deleted_at.is_(None))
        .group_by(Analysis.document_id)
        .order_by(func.max(Analysis.created_at).desc())
        .limit(200)
    ).all()
    documents: list[Document] = []
    seen: set[UUID] = set()
    for (document_id,) in rows:
        if document_id in seen:
            continue
        seen.add(document_id)
        try:
            documents.append(get_document_for_actor(db=db, actor=admin, document_id=document_id))
        except DocumentNotFoundError:
            continue
    return documents


def _latest_analysis_statuses_through_analysis_lookup(
    *,
    db: Session,
    document_ids: list[UUID],
) -> dict[UUID, AnalysisStatusRead]:
    if not document_ids:
        return {}

    chain_cancel_requested = (
        Analysis.run_parameters[ANALYSIS_CHAIN_CANCEL_REQUESTED_AT_KEY]
        .as_string()
        .is_not(None)
        .label("chain_cancel_requested")
    )
    ranked = (
        select(
            Analysis.id.label("id"),
            Analysis.document_id.label("document_id"),
            Analysis.skill_id.label("skill_id"),
            Analysis.skill_version.label("skill_version"),
            Analysis.provider.label("provider"),
            Analysis.model.label("model"),
            Analysis.status.label("status"),
            Analysis.verdict.label("verdict"),
            Analysis.error_message.label("error_message"),
            chain_cancel_requested,
            Analysis.created_at.label("created_at"),
            Analysis.started_at.label("started_at"),
            Analysis.completed_at.label("completed_at"),
            func.row_number()
            .over(
                partition_by=Analysis.document_id,
                order_by=(
                    func.coalesce(Analysis.completed_at, Analysis.created_at).desc(),
                    Analysis.created_at.desc(),
                    Analysis.id.desc(),
                ),
            )
            .label("status_rank"),
        )
        .where(
            Analysis.document_id.in_(document_ids),
            Analysis.deleted_at.is_(None),
        )
        .subquery()
    )
    rows = db.execute(select(ranked).where(ranked.c.status_rank == 1)).mappings().all()
    sources = [
        AnalysisStatusSource(
            id=row["id"],
            document_id=row["document_id"],
            skill_id=row["skill_id"],
            skill_version=row["skill_version"],
            provider=row["provider"],
            model=row["model"],
            status=row["status"],
            verdict=row["verdict"],
            error_message=row["error_message"],
            chain_cancel_requested=bool(row["chain_cancel_requested"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )
        for row in rows
    ]
    statuses = read_analysis_statuses(db=db, sources=sources)
    return {status.document_id: status for status in statuses}


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
        linked_fin_summary_document_id=document.linked_fin_summary_document_id,
        owner_login=owner.login,
        title=document.title,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        file_size_bytes=document.file_size_bytes,
        file_hash_sha256=document.file_hash_sha256,
        parse_status=document.parse_status,
        detected_document_type=document.detected_document_type,
        manual_document_type=document.manual_document_type,
        document_role=document.document_role,
        document_type_confidence=document.document_type_confidence,
        parse_error=document.parse_error,
        status=document.status,
        parsed_text_available=document.parsed_text is not None,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )

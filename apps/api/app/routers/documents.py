from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.dependencies.auth import require_current_user
from app.models.document import Document
from app.models.user import User
from app.schemas.documents import DocumentRead, DocumentsListResponse
from app.schemas.enums import DocumentType
from app.services.document_jobs import ParseDocumentEnqueue, enqueue_parse_document
from app.services.documents import (
    DocumentNotFoundError,
    DocumentTooLargeError,
    UnsupportedDocumentFileTypeError,
    create_document_from_upload,
    get_document_for_actor,
    list_documents_for_actor,
)
from app.storage.local import LocalDocumentStorage

router = APIRouter(prefix="/documents", tags=["documents"])


def get_document_storage() -> LocalDocumentStorage:
    return LocalDocumentStorage(get_settings().storage_root)


def get_parse_document_enqueue() -> ParseDocumentEnqueue:
    return enqueue_parse_document


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def create_document(
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    manual_document_type: Annotated[DocumentType | None, Form()] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
    storage: LocalDocumentStorage = Depends(get_document_storage),
    enqueue: ParseDocumentEnqueue = Depends(get_parse_document_enqueue),
) -> Document:
    try:
        document = create_document_from_upload(
            db=db,
            actor=current_user,
            storage=storage,
            upload=file,
            title=title,
            manual_document_type=manual_document_type,
        )
        enqueue(document.id)
        return document
    except UnsupportedDocumentFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported document file type",
        ) from exc
    except DocumentTooLargeError as exc:
        raise HTTPException(
            status_code=413,
            detail="File exceeds maximum upload size",
        ) from exc


@router.get("", response_model=DocumentsListResponse)
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> DocumentsListResponse:
    return DocumentsListResponse(documents=list_documents_for_actor(db=db, actor=current_user))


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Document:
    try:
        return get_document_for_actor(db=db, actor=current_user, document_id=document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc

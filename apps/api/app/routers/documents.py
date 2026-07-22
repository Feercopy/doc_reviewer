from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.dependencies.auth import require_current_user
from app.models.document import Document
from app.models.user import User
from app.schemas.documents import DocumentRead, DocumentTitlePatch, DocumentTypePatch, DocumentsListResponse
from app.schemas.enums import DocumentParseStatus, DocumentType
from app.services.document_jobs import ParseDocumentEnqueue, enqueue_parse_document
from app.services.documents import (
    DocumentNotFoundError,
    DocumentReparseNotSupportedError,
    DocumentTooLargeError,
    UnsupportedDocumentFileTypeError,
    cleanup_uploaded_document_bundle,
    create_uploaded_document_bundle,
    delete_document_for_actor,
    get_document_for_actor,
    list_documents_for_actor,
    reset_document_for_reparse,
    update_document_title,
    update_manual_document_type,
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
    fin_summary_file: Annotated[UploadFile | None, File()] = None,
    title: Annotated[str | None, Form()] = None,
    manual_document_type: Annotated[DocumentType | None, Form()] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
    storage: LocalDocumentStorage = Depends(get_document_storage),
    enqueue: ParseDocumentEnqueue = Depends(get_parse_document_enqueue),
) -> Document:
    try:
        bundle = create_uploaded_document_bundle(
            db=db,
            actor=current_user,
            storage=storage,
            primary_upload=file,
            fin_summary_upload=fin_summary_file,
            title=title,
            manual_document_type=manual_document_type,
        )
        try:
            for document_id in bundle.enqueued_document_ids:
                enqueue(document_id)
        except Exception as exc:
            cleanup_uploaded_document_bundle(db=db, storage=storage, primary_document_id=bundle.primary_document.id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to enqueue document parsing",
            ) from exc
        return bundle.primary_document
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


@router.patch("/{document_id}/document-type", response_model=DocumentRead)
def patch_document_type(
    document_id: UUID,
    payload: DocumentTypePatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Document:
    try:
        return update_manual_document_type(
            db=db,
            actor=current_user,
            document_id=document_id,
            manual_document_type=payload.manual_document_type,
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc


@router.patch("/{document_id}/title", response_model=DocumentRead)
def patch_document_title(
    document_id: UUID,
    payload: DocumentTitlePatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Document:
    try:
        return update_document_title(db=db, actor=current_user, document_id=document_id, title=payload.title)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> None:
    try:
        delete_document_for_actor(db=db, actor=current_user, document_id=document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc


@router.get("/{document_id}/parsed-text", response_class=PlainTextResponse)
def get_parsed_text(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> PlainTextResponse:
    try:
        document = get_document_for_actor(db=db, actor=current_user, document_id=document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc

    if document.parse_status != DocumentParseStatus.COMPLETED.value or document.parsed_text is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Parsed text is not available")

    return PlainTextResponse(document.parsed_text)


@router.get("/{document_id}/raw")
def get_raw_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> FileResponse:
    try:
        document = get_document_for_actor(db=db, actor=current_user, document_id=document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc

    return FileResponse(document.storage_path, filename=document.original_filename, media_type=document.mime_type)


@router.post("/{document_id}/reparse", response_model=DocumentRead)
def reparse_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
    enqueue: ParseDocumentEnqueue = Depends(get_parse_document_enqueue),
) -> Document:
    try:
        document = reset_document_for_reparse(db=db, actor=current_user, document_id=document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc
    except DocumentReparseNotSupportedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    enqueue(document.id)
    return document

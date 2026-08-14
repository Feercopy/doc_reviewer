from pathlib import Path
from uuid import UUID
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.dependencies.auth import require_current_user
from app.models.etalon import Etalon
from app.models.user import User
from app.schemas.enums import DocumentType, Verdict
from app.schemas.etalons import (
    EtalonDraftCreate,
    EtalonRead,
    EtalonsListResponse,
    EtalonUpdate,
    Gate2BenchmarkImportRequest,
    Gate2BenchmarkImportResponse,
)
from app.services.document_jobs import ParseDocumentEnqueue, enqueue_parse_document
from app.services.analyses import AnalysisNotFoundError
from app.services.documents import DocumentTooLargeError, UnsupportedDocumentFileTypeError
from app.services.etalons import (
    EtalonForbiddenError,
    EtalonNotFoundError,
    EtalonPreconditionError,
    archive_etalon,
    create_etalon_draft_from_analysis,
    create_past_defense_etalon,
    get_etalon_for_actor,
    import_gate2_benchmark_etalons,
    list_annotation_queue,
    list_etalons_for_actor,
    publish_etalon,
    update_etalon,
)
from app.storage.local import LocalDocumentStorage

router = APIRouter(tags=["etalons"])


def get_document_storage() -> LocalDocumentStorage:
    return LocalDocumentStorage(get_settings().storage_root)


def get_parse_document_enqueue() -> ParseDocumentEnqueue:
    return enqueue_parse_document


@router.get("/etalons", response_model=EtalonsListResponse)
def list_etalons(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> EtalonsListResponse:
    return EtalonsListResponse(etalons=list_etalons_for_actor(db=db, actor=current_user))


@router.post("/etalons/import/gate2-benchmark", response_model=Gate2BenchmarkImportResponse)
def import_gate2_benchmark(
    payload: Gate2BenchmarkImportRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
    storage: LocalDocumentStorage = Depends(get_document_storage),
    enqueue: ParseDocumentEnqueue = Depends(get_parse_document_enqueue),
) -> Gate2BenchmarkImportResponse:
    try:
        result = import_gate2_benchmark_etalons(
            db=db,
            actor=current_user,
            storage=storage,
            benchmark_dir=Path(payload.benchmark_dir) if payload.benchmark_dir else get_settings().gate2_benchmark_dir,
            activate=payload.activate,
        )
    except EtalonForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (EtalonPreconditionError, FileNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    enqueued_ids = []
    for document_id in dict.fromkeys(result.parse_document_ids):
        enqueue(document_id)
        enqueued_ids.append(document_id)
    response.status_code = status.HTTP_201_CREATED if result.imported_count else status.HTTP_200_OK
    return Gate2BenchmarkImportResponse(
        imported_count=result.imported_count,
        skipped_count=result.skipped_count,
        updated_count=result.updated_count,
        unmatched_count=result.unmatched_count,
        parse_enqueued_count=len(enqueued_ids),
        etalons=result.etalons,
    )


@router.get("/etalons/{etalon_id}", response_model=EtalonRead)
def get_etalon(
    etalon_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Etalon:
    try:
        return get_etalon_for_actor(db=db, actor=current_user, etalon_id=etalon_id)
    except EtalonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Etalon not found") from exc


@router.patch("/etalons/{etalon_id}", response_model=EtalonRead)
def patch_etalon(
    etalon_id: UUID,
    payload: EtalonUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Etalon:
    try:
        return update_etalon(db=db, actor=current_user, etalon_id=etalon_id, payload=payload)
    except EtalonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Etalon not found") from exc
    except EtalonForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except EtalonPreconditionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/etalons/{etalon_id}/publish", response_model=EtalonRead)
def post_publish_etalon(
    etalon_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Etalon:
    try:
        return publish_etalon(db=db, actor=current_user, etalon_id=etalon_id)
    except EtalonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Etalon not found") from exc
    except EtalonForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except EtalonPreconditionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/etalons/{etalon_id}/archive", response_model=EtalonRead)
def post_archive_etalon(
    etalon_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Etalon:
    try:
        return archive_etalon(db=db, actor=current_user, etalon_id=etalon_id)
    except EtalonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Etalon not found") from exc
    except EtalonForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/annotation/queue", response_model=EtalonsListResponse)
def get_annotation_queue(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> EtalonsListResponse:
    try:
        return EtalonsListResponse(etalons=list_annotation_queue(db=db, actor=current_user))
    except EtalonForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/documents/past-defense", response_model=EtalonRead, status_code=status.HTTP_201_CREATED)
def create_past_defense(
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    document_type: Annotated[DocumentType, Form()] = DocumentType.UNKNOWN,
    expected_verdict: Annotated[Verdict, Form()] = Verdict.UNKNOWN,
    real_defense_status: Annotated[str, Form()] = "",
    defense_date: Annotated[str | None, Form()] = None,
    defense_comments: Annotated[str, Form()] = "",
    notes: Annotated[str | None, Form()] = None,
    raw_file_visible_to_all: Annotated[bool, Form()] = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
    storage: LocalDocumentStorage = Depends(get_document_storage),
    enqueue: ParseDocumentEnqueue = Depends(get_parse_document_enqueue),
) -> Etalon:
    try:
        document, etalon = create_past_defense_etalon(
            db=db,
            actor=current_user,
            storage=storage,
            upload=file,
            title=title,
            document_type=document_type,
            expected_verdict=expected_verdict,
            real_defense_status=real_defense_status,
            defense_comments=defense_comments,
            defense_date=defense_date,
            notes=notes,
            raw_file_visible_to_all=raw_file_visible_to_all,
        )
    except UnsupportedDocumentFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported document file type",
        ) from exc
    except DocumentTooLargeError as exc:
        raise HTTPException(status_code=413, detail="File exceeds maximum upload size") from exc

    enqueue(document.id)
    return etalon


@router.post("/analyses/{analysis_id}/etalon-draft", response_model=EtalonRead, status_code=status.HTTP_201_CREATED)
def create_etalon_draft(
    analysis_id: UUID,
    payload: EtalonDraftCreate | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Etalon:
    try:
        return create_etalon_draft_from_analysis(
            db=db,
            actor=current_user,
            analysis_id=analysis_id,
            payload=payload or EtalonDraftCreate(),
        )
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found") from exc
    except EtalonForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except EtalonPreconditionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

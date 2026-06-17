from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_current_user
from app.models.analysis import Analysis
from app.models.user import User
from app.schemas.analyses import AnalysesListResponse, AnalysisCreate, AnalysisDetailRunRead, AnalysisRead
from app.services.analyses import (
    AnalysisNotFoundError,
    AnalysisPreconditionError,
    create_analysis_for_document,
    delete_analysis_for_actor,
    get_latest_analysis_detail_run_for_actor,
    get_analysis_for_actor,
    list_document_analyses_for_actor,
    read_analysis,
    read_analysis_detail_run,
    request_analysis_detail_run,
)
from app.services.analysis_jobs import (
    RunAnalysisDetailsEnqueue,
    RunAnalysisEnqueue,
    enqueue_run_analysis,
    enqueue_run_analysis_details,
)
from app.services.documents import DocumentNotFoundError

router = APIRouter(tags=["analyses"])


def get_run_analysis_enqueue() -> RunAnalysisEnqueue:
    return enqueue_run_analysis


def get_run_analysis_details_enqueue() -> RunAnalysisDetailsEnqueue:
    return enqueue_run_analysis_details


@router.post("/documents/{document_id}/analyses", response_model=AnalysisRead, status_code=status.HTTP_201_CREATED)
def create_analysis(
    document_id: UUID,
    payload: AnalysisCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
    enqueue: RunAnalysisEnqueue = Depends(get_run_analysis_enqueue),
) -> AnalysisRead:
    try:
        analysis = create_analysis_for_document(
            db=db,
            actor=current_user,
            document_id=document_id,
            provider=payload.provider,
            model=payload.model,
            skill_id=payload.skill_id,
            document_type_override=payload.document_type_override,
            run_parameters=payload.run_parameters,
        )
    except AnalysisPreconditionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc

    enqueue(analysis.id)
    return read_analysis(db=db, actor=current_user, analysis=analysis)


@router.get("/documents/{document_id}/analyses", response_model=AnalysesListResponse)
def list_document_analyses(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> AnalysesListResponse:
    try:
        analyses = list_document_analyses_for_actor(db=db, actor=current_user, document_id=document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc
    return AnalysesListResponse(analyses=[read_analysis(db=db, actor=current_user, analysis=item) for item in analyses])


@router.get("/analyses/{analysis_id}", response_model=AnalysisRead)
def get_analysis(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> AnalysisRead:
    try:
        analysis = get_analysis_for_actor(db=db, actor=current_user, analysis_id=analysis_id)
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found") from exc
    return read_analysis(db=db, actor=current_user, analysis=analysis)


@router.delete("/analyses/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> None:
    try:
        delete_analysis_for_actor(db=db, actor=current_user, analysis_id=analysis_id)
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found") from exc


@router.post("/analyses/{analysis_id}/details", response_model=AnalysisDetailRunRead)
def create_analysis_details(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
    enqueue: RunAnalysisDetailsEnqueue = Depends(get_run_analysis_details_enqueue),
) -> AnalysisDetailRunRead:
    try:
        detail_run = request_analysis_detail_run(db=db, actor=current_user, analysis_id=analysis_id)
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found") from exc
    except AnalysisPreconditionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if getattr(detail_run, "created_for_request", False):
        enqueue(detail_run.id)
    return read_analysis_detail_run(actor=current_user, detail_run=detail_run)


@router.get("/analyses/{analysis_id}/details", response_model=AnalysisDetailRunRead)
def get_analysis_details(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> AnalysisDetailRunRead:
    try:
        detail_run = get_latest_analysis_detail_run_for_actor(db=db, actor=current_user, analysis_id=analysis_id)
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis detail run not found") from exc
    return read_analysis_detail_run(actor=current_user, detail_run=detail_run)

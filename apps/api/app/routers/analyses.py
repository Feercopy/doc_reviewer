from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_current_user
from app.models.analysis import Analysis
from app.models.user import User
from app.schemas.analyses import (
    AnalysesListResponse,
    AnalysisCreate,
    AnalysisDetailRunRead,
    AnalysisRead,
    AnalysisStatusesListResponse,
    AnalysisStatusRead,
    NewSummaryRead,
    SummaryLocalizationsRead,
)
from app.services.analyses import (
    AnalysisNotFoundError,
    AnalysisPreconditionError,
    cancel_analysis_for_actor,
    create_analysis_for_document,
    delete_document_analysis_results_for_actor,
    delete_analysis_for_actor,
    get_analysis_status_for_actor,
    get_latest_analysis_detail_run_for_actor,
    get_analysis_for_actor,
    list_document_analysis_statuses_for_actor,
    list_document_analyses_for_actor,
    read_analysis,
    read_analysis_detail_run,
    request_analysis_detail_run,
)
from app.services.analysis_jobs import (
    RunAnalysisDetailsEnqueue,
    RunAnalysisEnqueue,
    RunSummaryLocalizationsEnqueue,
    enqueue_run_analysis,
    enqueue_run_analysis_details,
    enqueue_run_summary_localizations,
)
from app.services.documents import DocumentNotFoundError
from app.services.new_summaries import (
    mark_new_summary_enqueue_failed,
    request_new_summary,
)
from app.services.summary_localizations import (
    mark_summary_localizations_enqueue_failed,
    read_summary_localizations,
    request_summary_localizations,
)

router = APIRouter(tags=["analyses"])


def get_run_analysis_enqueue() -> RunAnalysisEnqueue:
    return enqueue_run_analysis


def get_run_analysis_details_enqueue() -> RunAnalysisDetailsEnqueue:
    return enqueue_run_analysis_details


def get_run_summary_localizations_enqueue() -> RunSummaryLocalizationsEnqueue:
    return enqueue_run_summary_localizations


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


@router.get("/documents/{document_id}/analyses/statuses", response_model=AnalysisStatusesListResponse)
def list_document_analysis_statuses(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> AnalysisStatusesListResponse:
    try:
        analyses = list_document_analysis_statuses_for_actor(
            db=db,
            actor=current_user,
            document_id=document_id,
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc
    return AnalysisStatusesListResponse(analyses=analyses)


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


@router.get("/analyses/{analysis_id}/status", response_model=AnalysisStatusRead)
def get_analysis_status(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> AnalysisStatusRead:
    try:
        return get_analysis_status_for_actor(db=db, actor=current_user, analysis_id=analysis_id)
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found") from exc


@router.get("/analyses/{analysis_id}/summary-localizations", response_model=SummaryLocalizationsRead)
def get_analysis_summary_localizations(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> SummaryLocalizationsRead:
    try:
        analysis = get_analysis_for_actor(db=db, actor=current_user, analysis_id=analysis_id)
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found") from exc
    return read_summary_localizations(analysis)


@router.post("/analyses/{analysis_id}/summary-localizations", response_model=SummaryLocalizationsRead)
def ensure_analysis_summary_localizations(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
    enqueue: RunSummaryLocalizationsEnqueue = Depends(get_run_summary_localizations_enqueue),
) -> SummaryLocalizationsRead:
    try:
        analysis = get_analysis_for_actor(db=db, actor=current_user, analysis_id=analysis_id)
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found") from exc
    response, should_enqueue = request_summary_localizations(db=db, analysis=analysis)
    if should_enqueue:
        try:
            enqueue(analysis.id)
        except Exception as exc:
            mark_summary_localizations_enqueue_failed(
                db=db,
                analysis=analysis,
                error_message="summary_generation_queue_unavailable",
            )
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Summary generation queue is unavailable") from exc
    return response


@router.get("/analyses/{analysis_id}/new-summary", response_model=NewSummaryRead)
def get_analysis_new_summary(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
    enqueue: RunSummaryLocalizationsEnqueue = Depends(get_run_summary_localizations_enqueue),
) -> NewSummaryRead:
    try:
        analysis = get_analysis_for_actor(db=db, actor=current_user, analysis_id=analysis_id)
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found") from exc
    response, should_enqueue = request_new_summary(db=db, analysis=analysis)
    if should_enqueue:
        try:
            enqueue(analysis.id)
        except Exception as exc:
            mark_new_summary_enqueue_failed(
                db=db,
                analysis=analysis,
                error_message="new_summary_generation_queue_unavailable",
            )
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="New Summary generation queue is unavailable") from exc
    return response


@router.post("/analyses/{analysis_id}/new-summary", response_model=NewSummaryRead)
def ensure_analysis_new_summary(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
    enqueue: RunSummaryLocalizationsEnqueue = Depends(get_run_summary_localizations_enqueue),
) -> NewSummaryRead:
    try:
        analysis = get_analysis_for_actor(db=db, actor=current_user, analysis_id=analysis_id)
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found") from exc
    response, should_enqueue = request_new_summary(db=db, analysis=analysis, create_if_missing=True)
    if should_enqueue:
        try:
            enqueue(analysis.id)
        except Exception as exc:
            mark_new_summary_enqueue_failed(
                db=db,
                analysis=analysis,
                error_message="new_summary_generation_queue_unavailable",
            )
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="New Summary generation queue is unavailable") from exc
    return response


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
    except AnalysisPreconditionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/documents/{document_id}/analyses", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_analysis_results(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> None:
    try:
        delete_document_analysis_results_for_actor(db=db, actor=current_user, document_id=document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found") from exc
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found") from exc
    except AnalysisPreconditionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/analyses/{analysis_id}/cancel", response_model=AnalysisRead)
def cancel_analysis(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> AnalysisRead:
    try:
        analysis = cancel_analysis_for_actor(db=db, actor=current_user, analysis_id=analysis_id)
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found") from exc
    return read_analysis(db=db, actor=current_user, analysis=analysis)


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

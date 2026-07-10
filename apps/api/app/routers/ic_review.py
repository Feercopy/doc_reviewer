from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_current_user
from app.models.user import User
from app.schemas.analyses import AnalysisCheckRunRead, AnalysisCheckRunsListResponse
from app.schemas.enums import Provider
from app.services.analyses import AnalysisNotFoundError, AnalysisPreconditionError
from app.services.analysis_jobs import RunIcAgenticReviewEnqueue, enqueue_run_ic_agentic_review
from app.services.ic_review import (
    IcReviewRunNotFoundError,
    IcReviewWorkbookTooLargeError,
    UnsupportedWorkbookFileTypeError,
    artifact_path_for_actor,
    create_ic_review_run_for_analysis,
    get_ic_review_run_for_actor,
    latest_ic_review_run_for_analysis,
    list_ic_review_runs_for_analysis,
    mark_ic_review_run_enqueue_failed,
    read_ic_review_run,
)

router = APIRouter(tags=["ic-review"])


def get_run_ic_agentic_review_enqueue() -> RunIcAgenticReviewEnqueue:
    return enqueue_run_ic_agentic_review


@router.post(
    "/analyses/{analysis_id}/ic-review-runs",
    response_model=AnalysisCheckRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_ic_review_run(
    analysis_id: UUID,
    provider: Provider = Form(...),
    model: str = Form(...),
    output_language: str = Form("ru"),
    financial_model: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
    enqueue: RunIcAgenticReviewEnqueue = Depends(get_run_ic_agentic_review_enqueue),
) -> AnalysisCheckRunRead:
    try:
        run = create_ic_review_run_for_analysis(
            db=db,
            actor=current_user,
            analysis_id=analysis_id,
            provider=provider,
            model=model,
            output_language=output_language,
            financial_model=financial_model,
        )
    except AnalysisNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found") from exc
    except UnsupportedWorkbookFileTypeError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc
    except IcReviewWorkbookTooLargeError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except AnalysisPreconditionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    try:
        enqueue(run.id)
    except Exception as exc:
        mark_ic_review_run_enqueue_failed(db=db, run_id=run.id, error_message=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue IC review run",
        ) from exc
    return read_ic_review_run(db=db, actor=current_user, run=run)


@router.get("/analyses/{analysis_id}/ic-review-runs", response_model=AnalysisCheckRunsListResponse)
def list_ic_review_runs(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> AnalysisCheckRunsListResponse:
    try:
        runs = list_ic_review_runs_for_analysis(db=db, actor=current_user, analysis_id=analysis_id)
    except AnalysisNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found") from exc
    return AnalysisCheckRunsListResponse(runs=[read_ic_review_run(db=db, actor=current_user, run=run) for run in runs])


@router.get("/analyses/{analysis_id}/ic-review-runs/latest", response_model=AnalysisCheckRunRead)
def get_latest_ic_review_run(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> AnalysisCheckRunRead:
    try:
        run = latest_ic_review_run_for_analysis(db=db, actor=current_user, analysis_id=analysis_id)
    except (AnalysisNotFoundError, IcReviewRunNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IC review run not found") from exc
    return read_ic_review_run(db=db, actor=current_user, run=run)


@router.get("/ic-review-runs/{run_id}", response_model=AnalysisCheckRunRead)
def get_ic_review_run(
    run_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> AnalysisCheckRunRead:
    try:
        run = get_ic_review_run_for_actor(db=db, actor=current_user, run_id=run_id)
    except IcReviewRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IC review run not found") from exc
    return read_ic_review_run(db=db, actor=current_user, run=run)


@router.get("/ic-review-runs/{run_id}/artifacts/{artifact_key}")
def download_ic_review_artifact(
    run_id: UUID,
    artifact_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> FileResponse:
    try:
        path, filename, media_type = artifact_path_for_actor(
            db=db,
            actor=current_user,
            run_id=run_id,
            artifact_key=artifact_key,
        )
    except IcReviewRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found") from exc
    return FileResponse(path, media_type=media_type, filename=filename)

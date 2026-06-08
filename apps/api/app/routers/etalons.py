from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_current_user
from app.models.etalon import Etalon
from app.models.user import User
from app.schemas.etalons import EtalonDraftCreate, EtalonRead, EtalonsListResponse, EtalonUpdate
from app.services.analyses import AnalysisNotFoundError
from app.services.etalons import (
    EtalonForbiddenError,
    EtalonNotFoundError,
    EtalonPreconditionError,
    archive_etalon,
    create_etalon_draft_from_analysis,
    get_etalon_for_actor,
    list_annotation_queue,
    list_etalons_for_actor,
    publish_etalon,
    update_etalon,
)

router = APIRouter(tags=["etalons"])


@router.get("/etalons", response_model=EtalonsListResponse)
def list_etalons(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> EtalonsListResponse:
    return EtalonsListResponse(etalons=list_etalons_for_actor(db=db, actor=current_user))


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

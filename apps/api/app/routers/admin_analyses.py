from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_admin
from app.models.analysis import Analysis
from app.models.document import Document
from app.models.skill import Skill
from app.models.user import User
from app.schemas.admin import AdminAnalysesListResponse, AdminAnalysisRead
from app.schemas.enums import Provider, RunStatus

router = APIRouter(prefix="/admin/analyses", tags=["admin-analyses"])


@router.get("", response_model=AdminAnalysesListResponse)
def list_admin_analyses(
    provider: Provider | None = None,
    model: str | None = None,
    skill_id: UUID | None = None,
    status: RunStatus | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminAnalysesListResponse:
    statement = (
        select(Analysis, Document, User, Skill)
        .join(Document, Document.id == Analysis.document_id)
        .join(User, User.id == Analysis.user_id)
        .join(Skill, Skill.id == Analysis.skill_id)
        .where(Analysis.deleted_at.is_(None))
    )
    if provider is not None:
        statement = statement.where(Analysis.provider == provider.value)
    if model is not None:
        statement = statement.where(Analysis.model == model)
    if skill_id is not None:
        statement = statement.where(Analysis.skill_id == skill_id)
    if status is not None:
        statement = statement.where(Analysis.status == status.value)
    statement = statement.order_by(Analysis.created_at.desc())
    return AdminAnalysesListResponse(
        analyses=[_read_analysis(analysis, document, user, skill) for analysis, document, user, skill in db.execute(statement).all()]
    )


@router.get("/{analysis_id}", response_model=AdminAnalysisRead)
def get_admin_analysis(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminAnalysisRead:
    row = db.execute(
        select(Analysis, Document, User, Skill)
        .join(Document, Document.id == Analysis.document_id)
        .join(User, User.id == Analysis.user_id)
        .join(Skill, Skill.id == Analysis.skill_id)
        .where(Analysis.id == analysis_id, Analysis.deleted_at.is_(None))
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
    analysis, document, user, skill = row
    return _read_analysis(analysis, document, user, skill)


def _read_analysis(analysis: Analysis, document: Document, user: User, skill: Skill) -> AdminAnalysisRead:
    return AdminAnalysisRead(
        id=analysis.id,
        document_id=analysis.document_id,
        document_title=document.title,
        user_id=analysis.user_id,
        user_login=user.login,
        skill_id=analysis.skill_id,
        skill_name=skill.name,
        skill_version=analysis.skill_version,
        provider=analysis.provider,
        model=analysis.model,
        status=analysis.status,
        verdict=analysis.verdict,
        summary=analysis.summary,
        structured_output=analysis.structured_output,
        raw_output=analysis.raw_output,
        error_message=analysis.error_message,
        latency_ms=analysis.latency_ms,
        input_tokens=analysis.input_tokens,
        output_tokens=analysis.output_tokens,
        estimated_cost=analysis.estimated_cost,
        run_parameters=analysis.run_parameters,
        created_at=analysis.created_at,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
    )

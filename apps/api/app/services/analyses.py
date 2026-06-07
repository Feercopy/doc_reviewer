from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authz.policies import can_read_analysis
from app.core.config import get_settings
from app.models.analysis import Analysis, PredictedCommentRun
from app.models.document import Document
from app.models.skill import Skill
from app.models.user import User
from app.schemas.analyses import AnalysisRead, PredictedCommentRunRead
from app.schemas.enums import DocumentParseStatus, DocumentType, EntityStatus, Provider, RunStatus, SkillType
from app.services.documents import DocumentNotFoundError, get_document_for_actor
from app.services.provider_keys import get_provider_key
from app.services.skills import skill_source_snapshot


class AnalysisNotFoundError(ValueError):
    pass


class AnalysisPreconditionError(ValueError):
    pass


def create_analysis_for_document(
    *,
    db: Session,
    actor: User,
    document_id: UUID,
    provider: Provider,
    model: str,
    skill_id: UUID | None,
    document_type_override: DocumentType | None,
    run_parameters: dict,
) -> Analysis:
    document = get_document_for_actor(db=db, actor=actor, document_id=document_id)
    if document.parse_status != DocumentParseStatus.COMPLETED.value or not document.parsed_text:
        raise AnalysisPreconditionError("Document parse is not completed")

    document_type = (
        document_type_override.value
        if document_type_override
        else document.manual_document_type or document.detected_document_type
    )
    skill = _resolve_skill(db=db, skill_id=skill_id, document_type=document_type)
    if provider != Provider.HERMES and get_provider_key(db=db, owner_id=actor.id, provider=provider) is None:
        raise AnalysisPreconditionError("Provider key is not configured")
    if provider == Provider.HERMES and not get_settings().hermes_enabled:
        raise AnalysisPreconditionError("Hermes provider is disabled")

    merged_parameters = dict(run_parameters)
    merged_parameters["document_type"] = document_type
    merged_parameters["skill_source_snapshot"] = skill_source_snapshot(skill)

    analysis = Analysis(
        document_id=document.id,
        user_id=actor.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=provider.value,
        model=model,
        status=RunStatus.QUEUED.value,
        run_parameters=merged_parameters,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def get_analysis_for_actor(*, db: Session, actor: User, analysis_id: UUID) -> Analysis:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or not can_read_analysis(actor, analysis):
        raise AnalysisNotFoundError("Analysis not found")
    return analysis


def list_document_analyses_for_actor(*, db: Session, actor: User, document_id: UUID) -> list[Analysis]:
    document = get_document_for_actor(db=db, actor=actor, document_id=document_id)
    statement = select(Analysis).where(Analysis.document_id == document.id).order_by(Analysis.created_at.desc())
    return list(db.execute(statement).scalars().all())


def read_analysis(*, db: Session, actor: User, analysis: Analysis) -> AnalysisRead:
    skill = db.get(Skill, analysis.skill_id)
    predicted_run = _latest_predicted_comment_run(db=db, analysis_id=analysis.id)
    return AnalysisRead(
        id=analysis.id,
        document_id=analysis.document_id,
        user_id=analysis.user_id,
        skill_id=analysis.skill_id,
        skill_name=skill.name if skill else "unknown",
        skill_version=analysis.skill_version,
        provider=analysis.provider,
        model=analysis.model,
        status=analysis.status,
        verdict=analysis.verdict,
        summary=analysis.summary,
        structured_output=analysis.structured_output,
        raw_output=analysis.raw_output if actor.role == "admin" else None,
        error_message=analysis.error_message,
        latency_ms=analysis.latency_ms,
        input_tokens=analysis.input_tokens,
        output_tokens=analysis.output_tokens,
        estimated_cost=analysis.estimated_cost,
        run_parameters=analysis.run_parameters,
        created_at=analysis.created_at,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
        predicted_comment_run=(
            _read_predicted_comment_run(db=db, actor=actor, predicted_run=predicted_run) if predicted_run else None
        ),
    )


def _resolve_skill(*, db: Session, skill_id: UUID | None, document_type: str) -> Skill:
    if skill_id is not None:
        skill = db.get(Skill, skill_id)
        if skill is None or skill.status != EntityStatus.ACTIVE.value or skill.skill_type != SkillType.MAIN_ANALYSIS.value:
            raise AnalysisPreconditionError("Selected skill is not available")
        return skill

    statement = select(Skill).where(
        Skill.status == EntityStatus.ACTIVE.value,
        Skill.skill_type == SkillType.MAIN_ANALYSIS.value,
    )
    if document_type == DocumentType.GATE_2.value:
        statement = statement.where(Skill.name == "gate2_challenger_main_analysis")
    skill = db.execute(statement.order_by(Skill.created_at.desc())).scalars().first()
    if skill is None:
        raise AnalysisPreconditionError("No active main analysis skill is available")
    return skill


def _latest_predicted_comment_run(*, db: Session, analysis_id: UUID) -> PredictedCommentRun | None:
    statement = (
        select(PredictedCommentRun)
        .where(PredictedCommentRun.analysis_id == analysis_id)
        .order_by(PredictedCommentRun.created_at.desc())
    )
    return db.execute(statement).scalars().first()


def _read_predicted_comment_run(
    *,
    db: Session,
    actor: User,
    predicted_run: PredictedCommentRun,
) -> PredictedCommentRunRead:
    skill = db.get(Skill, predicted_run.skill_id)
    return PredictedCommentRunRead(
        id=predicted_run.id,
        analysis_id=predicted_run.analysis_id,
        skill_id=predicted_run.skill_id,
        skill_name=skill.name if skill else "unknown",
        skill_version=predicted_run.skill_version,
        provider=predicted_run.provider,
        model=predicted_run.model,
        status=predicted_run.status,
        structured_output=predicted_run.structured_output,
        raw_output=predicted_run.raw_output if actor.role == "admin" else None,
        error_message=predicted_run.error_message,
        latency_ms=predicted_run.latency_ms,
        input_tokens=predicted_run.input_tokens,
        output_tokens=predicted_run.output_tokens,
        estimated_cost=predicted_run.estimated_cost,
        run_parameters=predicted_run.run_parameters,
        created_at=predicted_run.created_at,
        started_at=predicted_run.started_at,
        completed_at=predicted_run.completed_at,
    )

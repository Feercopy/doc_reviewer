from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authz.policies import can_read_analysis
from app.core.config import default_skill_source_snapshot_mode, get_settings
from app.models.base import utc_now
from app.models.analysis import Analysis, AnalysisDetailRun, PredictedCommentRun
from app.models.document import Document
from app.models.skill import Skill
from app.models.skill_source import SkillSource
from app.models.user import User
from app.schemas.analyses import AnalysisDetailRunRead, AnalysisRead, PredictedCommentRunRead, RetrievalTrace, SourceTrace
from app.schemas.enums import (
    GATE_CHALLENGER_DOCUMENT_TYPES,
    DocumentParseStatus,
    DocumentType,
    EntityStatus,
    Provider,
    RunStatus,
    SkillType,
)
from app.services.documents import DocumentNotFoundError, get_document_for_actor
from app.services.external_sources import SourceUnavailableError
from app.services.provider_keys import get_shared_provider_key
from app.schemas.provider_settings import normalize_available_models
from app.services.skill_snapshots import create_skill_source_snapshot
from app.services.skills import skill_source_snapshot
from app.services.audit import record_audit
from app.storage.local import LocalDocumentStorage


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
    if provider != Provider.HERMES:
        provider_key = get_shared_provider_key(db=db, provider=provider)
        if provider_key is None:
            raise AnalysisPreconditionError("Provider key is not configured")
        available_models = normalize_available_models(provider, provider_key.available_models, provider_key.default_model)
        if model not in available_models:
            raise AnalysisPreconditionError("Selected model is not available")
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
        run_parameters={},
    )
    db.add(analysis)
    db.flush()

    _attach_source_snapshot(
        db=db,
        analysis=analysis,
        skill=skill,
        run_parameters=merged_parameters,
    )
    analysis.run_parameters = merged_parameters
    record_audit(
        db=db,
        actor_id=actor.id,
        action="analysis.created",
        entity_type="analysis",
        entity_id=analysis.id,
        metadata={
            "document_id": str(document.id),
            "provider": provider.value,
            "model": model,
            "skill_id": str(skill.id),
            "skill_version": skill.version,
        },
    )
    db.commit()
    db.refresh(analysis)
    return analysis


def _attach_source_snapshot(
    *,
    db: Session,
    analysis: Analysis,
    skill: Skill,
    run_parameters: dict,
) -> None:
    if not skill.skill_source_id or skill.runtime_mode != "snapshot_required":
        return
    source = db.get(SkillSource, skill.skill_source_id)
    if source is None:
        raise AnalysisPreconditionError("Skill source is not configured")
    settings = get_settings()
    snapshot_mode = run_parameters.get("snapshot_mode") or default_skill_source_snapshot_mode(settings)
    storage = LocalDocumentStorage(settings.storage_root)
    try:
        snapshot = create_skill_source_snapshot(
            db=db,
            storage=storage,
            source=source,
            analysis_id=analysis.id,
            predicted_comment_run_id=None,
            snapshot_mode=snapshot_mode,
        )
    except SourceUnavailableError as exc:
        raise AnalysisPreconditionError(str(exc)) from exc

    run_parameters["source_snapshot_id"] = str(snapshot.id)
    run_parameters["source_fingerprint"] = snapshot.source_fingerprint
    run_parameters["source_revision"] = snapshot.resolved_revision
    run_parameters["source_snapshot_artifact_path"] = snapshot.artifact_path
    run_parameters["snapshot_mode"] = snapshot.snapshot_mode
    run_parameters["skill_source_snapshot"] = {
        **run_parameters.get("skill_source_snapshot", {}),
        "id": str(snapshot.id),
        "source_slug": snapshot.source_slug,
        "source_revision": snapshot.resolved_revision,
        "source_fingerprint": snapshot.source_fingerprint,
        "artifact_path": snapshot.artifact_path,
        "snapshot_mode": snapshot.snapshot_mode,
        "is_dirty": snapshot.is_dirty,
    }


def get_analysis_for_actor(*, db: Session, actor: User, analysis_id: UUID) -> Analysis:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or analysis.deleted_at is not None or not can_read_analysis(actor, analysis):
        raise AnalysisNotFoundError("Analysis not found")
    return analysis


def list_document_analyses_for_actor(*, db: Session, actor: User, document_id: UUID) -> list[Analysis]:
    document = get_document_for_actor(db=db, actor=actor, document_id=document_id)
    statement = (
        select(Analysis)
        .where(Analysis.document_id == document.id, Analysis.deleted_at.is_(None))
        .order_by(Analysis.created_at.desc())
    )
    return list(db.execute(statement).scalars().all())


def delete_analysis_for_actor(*, db: Session, actor: User, analysis_id: UUID) -> None:
    analysis = get_analysis_for_actor(db=db, actor=actor, analysis_id=analysis_id)
    analysis.deleted_at = utc_now()
    record_audit(
        db=db,
        actor_id=actor.id,
        action="analysis.deleted",
        entity_type="analysis",
        entity_id=analysis.id,
        metadata={
            "document_id": str(analysis.document_id),
            "previous_status": analysis.status,
        },
    )
    db.commit()


def read_analysis(*, db: Session, actor: User, analysis: Analysis) -> AnalysisRead:
    skill = db.get(Skill, analysis.skill_id)
    predicted_run = _latest_predicted_comment_run(db=db, analysis_id=analysis.id)
    detail_run = latest_analysis_detail_run(db=db, analysis_id=analysis.id)
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
        source_trace=_source_trace(analysis.run_parameters),
        created_at=analysis.created_at,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
        predicted_comment_run=(
            _read_predicted_comment_run(db=db, actor=actor, predicted_run=predicted_run) if predicted_run else None
        ),
        detail_run=_read_analysis_detail_run(actor=actor, detail_run=detail_run) if detail_run else None,
    )


def request_analysis_detail_run(*, db: Session, actor: User, analysis_id: UUID) -> AnalysisDetailRun:
    analysis = get_analysis_for_actor(db=db, actor=actor, analysis_id=analysis_id)
    if analysis.status != RunStatus.COMPLETED.value:
        raise AnalysisPreconditionError("Analysis is not completed")
    previous_response_id = (analysis.run_parameters or {}).get("gate_challenger_response_id")
    if not previous_response_id:
        raise AnalysisPreconditionError("Gate Challenger response id is missing")

    reusable_run = reusable_analysis_detail_run(db=db, analysis_id=analysis.id)
    if reusable_run is not None:
        reusable_run.created_for_request = False
        return reusable_run

    run_parameters = {
        "provider_api": "responses",
        "previous_response_id": previous_response_id,
        "output_language": (analysis.run_parameters or {}).get("output_language", "ru"),
        "source_snapshot_id": (analysis.run_parameters or {}).get("source_snapshot_id"),
        "source_fingerprint": (analysis.run_parameters or {}).get("source_fingerprint"),
        "source_revision": (analysis.run_parameters or {}).get("source_revision"),
        "skill_source_snapshot": (analysis.run_parameters or {}).get("skill_source_snapshot"),
    }
    detail_run = AnalysisDetailRun(
        analysis_id=analysis.id,
        status=RunStatus.QUEUED.value,
        provider=analysis.provider,
        model=analysis.model,
        previous_response_id=str(previous_response_id),
        run_parameters=run_parameters,
    )
    db.add(detail_run)
    db.commit()
    db.refresh(detail_run)
    detail_run.created_for_request = True
    return detail_run


def get_latest_analysis_detail_run_for_actor(
    *,
    db: Session,
    actor: User,
    analysis_id: UUID,
) -> AnalysisDetailRun:
    analysis = get_analysis_for_actor(db=db, actor=actor, analysis_id=analysis_id)
    detail_run = latest_analysis_detail_run(db=db, analysis_id=analysis.id)
    if detail_run is None:
        raise AnalysisNotFoundError("Analysis detail run not found")
    return detail_run


def latest_analysis_detail_run(*, db: Session, analysis_id: UUID) -> AnalysisDetailRun | None:
    statement = (
        select(AnalysisDetailRun)
        .where(AnalysisDetailRun.analysis_id == analysis_id)
        .order_by(AnalysisDetailRun.created_at.desc())
    )
    return db.execute(statement).scalars().first()


def reusable_analysis_detail_run(*, db: Session, analysis_id: UUID) -> AnalysisDetailRun | None:
    statement = (
        select(AnalysisDetailRun)
        .where(
            AnalysisDetailRun.analysis_id == analysis_id,
            AnalysisDetailRun.status.in_(
                [RunStatus.QUEUED.value, RunStatus.RUNNING.value, RunStatus.COMPLETED.value]
            ),
        )
        .order_by(AnalysisDetailRun.created_at.desc())
    )
    return db.execute(statement).scalars().first()


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
    gate_challenger_types = {item.value for item in GATE_CHALLENGER_DOCUMENT_TYPES}
    if document_type in gate_challenger_types:
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
        source_trace=_source_trace(predicted_run.run_parameters),
        retrieval_trace=_retrieval_trace(predicted_run.run_parameters),
        created_at=predicted_run.created_at,
        started_at=predicted_run.started_at,
        completed_at=predicted_run.completed_at,
    )


def read_analysis_detail_run(*, actor: User, detail_run: AnalysisDetailRun) -> AnalysisDetailRunRead:
    return _read_analysis_detail_run(actor=actor, detail_run=detail_run)


def _read_analysis_detail_run(*, actor: User, detail_run: AnalysisDetailRun) -> AnalysisDetailRunRead:
    return AnalysisDetailRunRead(
        id=detail_run.id,
        analysis_id=detail_run.analysis_id,
        status=detail_run.status,
        provider=detail_run.provider,
        model=detail_run.model,
        previous_response_id=detail_run.previous_response_id,
        response_id=detail_run.response_id,
        structured_output=detail_run.structured_output,
        raw_output=detail_run.raw_output if actor.role == "admin" else None,
        error_message=detail_run.error_message,
        latency_ms=detail_run.latency_ms,
        input_tokens=detail_run.input_tokens,
        output_tokens=detail_run.output_tokens,
        estimated_cost=detail_run.estimated_cost,
        run_parameters=detail_run.run_parameters,
        created_at=detail_run.created_at,
        started_at=detail_run.started_at,
        completed_at=detail_run.completed_at,
    )


def _source_trace(run_parameters: dict | None) -> SourceTrace | None:
    parameters = run_parameters or {}
    snapshot = parameters.get("skill_source_snapshot") or {}
    snapshot_id = parameters.get("source_snapshot_id") or parameters.get("skill_source_snapshot_id") or snapshot.get("id")
    source_fingerprint = parameters.get("source_fingerprint") or snapshot.get("source_fingerprint")
    if not snapshot_id and not source_fingerprint and not snapshot.get("source_slug"):
        return None
    return SourceTrace(
        source_snapshot_id=snapshot_id,
        source_slug=snapshot.get("source_slug"),
        source_revision=parameters.get("source_revision") or snapshot.get("source_revision"),
        source_fingerprint=source_fingerprint,
        snapshot_mode=parameters.get("snapshot_mode") or snapshot.get("snapshot_mode"),
        is_dirty=snapshot.get("is_dirty"),
        prompt_fingerprint=parameters.get("prompt_fingerprint"),
        rendered_prompt_artifact_path=parameters.get("rendered_prompt_artifact_path"),
    )


def _retrieval_trace(run_parameters: dict | None) -> RetrievalTrace | None:
    parameters = run_parameters or {}
    snapshot = parameters.get("retrieval_snapshot") or {}
    snapshot_id = parameters.get("retrieval_snapshot_id") or snapshot.get("id")
    if not snapshot_id and not snapshot.get("corpus_fingerprint"):
        return None
    return RetrievalTrace(
        retrieval_snapshot_id=snapshot_id,
        retrieval_mode=snapshot.get("retrieval_mode"),
        retrieval_version=snapshot.get("retrieval_version"),
        corpus_fingerprint=snapshot.get("corpus_fingerprint"),
        query_fingerprint=snapshot.get("query_fingerprint"),
        prompt_fingerprint=parameters.get("prompt_fingerprint"),
        rendered_prompt_artifact_path=parameters.get("rendered_prompt_artifact_path"),
    )

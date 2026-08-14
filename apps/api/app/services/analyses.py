from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.authz.policies import can_delete_analysis, can_read_analysis
from app.core.config import default_skill_source_snapshot_mode, get_settings
from app.models.base import utc_now
from app.models.analysis import Analysis, AnalysisCheckRun, AnalysisCheckStep, AnalysisDetailRun, PredictedCommentRun
from app.models.document import Document
from app.models.feedback import Feedback
from app.models.skill import Skill
from app.models.skill_source import RetrievalSnapshot, SkillSource, SkillSourceSnapshot
from app.models.user import User
from app.schemas.analyses import (
    AnalysisCheckRunStatusRead,
    AnalysisCheckStepStatusRead,
    AnalysisDetailRunRead,
    AnalysisRead,
    AnalysisStatusRead,
    PredictedCommentRunRead,
    RetrievalTrace,
    RunStatusSummaryRead,
    SourceTrace,
)
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


ACTIVE_RUN_STATUSES = {RunStatus.QUEUED.value, RunStatus.RUNNING.value}
ANALYSIS_CHAIN_CANCEL_REQUESTED_AT_KEY = "analysis_chain_cancel_requested_at"
ANALYSIS_CHAIN_CANCELLED_BY_USER_ID_KEY = "analysis_chain_cancelled_by_user_id"
MODEL_ANONYMIZATION_RUN_PARAMETER_KEY = "model_anonymization"
DOCUMENT_PARSE_DEPENDENCY_KEY = "document_parse_dependency"


@dataclass(frozen=True)
class AnalysisDeletionContext:
    analysis: Analysis
    predicted_runs: list[PredictedCommentRun]
    detail_runs: list[AnalysisDetailRun]
    check_runs: list[AnalysisCheckRun]
    check_steps: list[AnalysisCheckStep]


@dataclass(frozen=True)
class AnalysisStatusSource:
    id: UUID
    document_id: UUID
    skill_id: UUID
    skill_version: str
    provider: str
    model: str
    status: str
    verdict: str | None
    error_message: str | None
    chain_cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


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
    defer_until_document_parsed: bool = False,
) -> Analysis:
    document = get_document_for_actor(db=db, actor=actor, document_id=document_id)
    parse_completed = document.parse_status == DocumentParseStatus.COMPLETED.value and bool(document.parsed_text)
    if not parse_completed and not defer_until_document_parsed:
        raise AnalysisPreconditionError("Document parse is not completed")

    document_type = (
        document_type_override.value
        if document_type_override
        else document.manual_document_type or document.detected_document_type
    )
    if (
        document_type == DocumentType.PROGRESS_REVIEW.value
        and DocumentType.PROGRESS_REVIEW not in GATE_CHALLENGER_DOCUMENT_TYPES
    ):
        raise AnalysisPreconditionError("Progress Review analysis is not enabled yet")
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
    merged_parameters.setdefault("output_language", "ru")
    merged_parameters["document_type"] = document_type
    merged_parameters["skill_source_snapshot"] = skill_source_snapshot(skill)
    if not parse_completed:
        merged_parameters[DOCUMENT_PARSE_DEPENDENCY_KEY] = {
            "document_id": str(document.id),
            "state": "waiting",
        }

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
            analysis_check_run_id=None,
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
    if analysis is None or analysis.deleted_at is not None:
        raise AnalysisNotFoundError("Analysis not found")
    document = db.get(Document, analysis.document_id)
    if (
        document is None
        or document.status != EntityStatus.ACTIVE.value
        or not can_read_analysis(actor, analysis, document)
    ):
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


def list_document_analysis_statuses_for_actor(
    *,
    db: Session,
    actor: User,
    document_id: UUID,
) -> list[AnalysisStatusRead]:
    document = get_document_for_actor(db=db, actor=actor, document_id=document_id)
    statement = (
        _analysis_status_select()
        .where(Analysis.document_id == document.id, Analysis.deleted_at.is_(None))
        .order_by(Analysis.created_at.desc(), Analysis.id.desc())
    )
    sources = [_analysis_status_source(row) for row in db.execute(statement).mappings().all()]
    return read_analysis_statuses(db=db, sources=sources)


def get_analysis_status_for_actor(*, db: Session, actor: User, analysis_id: UUID) -> AnalysisStatusRead:
    statement = (
        _analysis_status_select()
        .join(Document, Document.id == Analysis.document_id)
        .where(
            Analysis.id == analysis_id,
            Analysis.deleted_at.is_(None),
            Document.status == EntityStatus.ACTIVE.value,
        )
    )
    if actor.role != "admin":
        statement = statement.where(Document.owner_id == actor.id)
    row = db.execute(statement).mappings().first()
    if row is None:
        raise AnalysisNotFoundError("Analysis not found")
    return read_analysis_statuses(db=db, sources=[_analysis_status_source(row)])[0]


def latest_document_analysis_statuses_for_actor(
    *,
    db: Session,
    actor: User,
    document_ids: list[UUID],
) -> dict[UUID, AnalysisStatusRead]:
    if not document_ids:
        return {}

    status_statement = _analysis_status_select().join(Document, Document.id == Analysis.document_id)
    if actor.role != "admin":
        status_statement = status_statement.where(Document.owner_id == actor.id)
    ranked = (
        status_statement
        .add_columns(
            func.row_number()
            .over(
                partition_by=Analysis.document_id,
                order_by=(
                    func.coalesce(Analysis.completed_at, Analysis.created_at).desc(),
                    Analysis.created_at.desc(),
                    Analysis.id.desc(),
                ),
            )
            .label("status_rank")
        )
        .where(
            Analysis.document_id.in_(document_ids),
            Analysis.deleted_at.is_(None),
        )
        .subquery()
    )
    rows = db.execute(select(ranked).where(ranked.c.status_rank == 1)).mappings().all()
    sources = [_analysis_status_source(row) for row in rows]
    statuses = read_analysis_statuses(db=db, sources=sources)
    return {status.document_id: status for status in statuses}


def latest_document_analyses_for_actor(
    *,
    db: Session,
    actor: User,
    document_ids: list[UUID],
) -> dict[UUID, Analysis]:
    if not document_ids:
        return {}

    statement = (
        select(Analysis)
        .where(
            Analysis.document_id.in_(document_ids),
            Analysis.deleted_at.is_(None),
        )
        .order_by(
            Analysis.document_id,
            func.coalesce(Analysis.completed_at, Analysis.created_at).desc(),
            Analysis.created_at.desc(),
        )
    )
    latest_by_document_id: dict[UUID, Analysis] = {}
    for analysis in db.execute(statement).scalars().all():
        if analysis.document_id in latest_by_document_id:
            continue
        document = db.get(Document, analysis.document_id)
        if document is None or not can_read_analysis(actor, analysis, document):
            continue
        latest_by_document_id[analysis.document_id] = analysis
    return latest_by_document_id


def read_analysis_statuses(*, db: Session, sources: list[AnalysisStatusSource]) -> list[AnalysisStatusRead]:
    if not sources:
        return []

    analysis_ids = [source.id for source in sources]
    skill_ids = {source.skill_id for source in sources}
    skill_names = {
        skill_id: name
        for skill_id, name in db.execute(select(Skill.id, Skill.name).where(Skill.id.in_(skill_ids))).all()
    }
    predicted_runs = _latest_run_status_summaries(
        db=db,
        model=PredictedCommentRun,
        analysis_ids=analysis_ids,
    )
    detail_runs = _latest_run_status_summaries(
        db=db,
        model=AnalysisDetailRun,
        analysis_ids=analysis_ids,
    )
    ic_review_runs = _latest_ic_review_status_summaries(db=db, analysis_ids=analysis_ids)
    source_traces = _analysis_source_traces(db=db, analysis_ids=analysis_ids)

    return [
        AnalysisStatusRead(
            id=source.id,
            document_id=source.document_id,
            skill_name=skill_names.get(source.skill_id, "unknown"),
            skill_version=source.skill_version,
            provider=source.provider,
            model=source.model,
            status=source.status,
            verdict=source.verdict,
            error_message=source.error_message,
            chain_cancel_requested=source.chain_cancel_requested,
            source_trace=source_traces.get(source.id),
            created_at=source.created_at,
            started_at=source.started_at,
            completed_at=source.completed_at,
            predicted_comment_run=predicted_runs.get(source.id),
            detail_run=detail_runs.get(source.id),
            ic_review_run=ic_review_runs.get(source.id),
        )
        for source in sources
    ]


def _analysis_status_select():
    chain_cancel_requested = (
        Analysis.run_parameters[ANALYSIS_CHAIN_CANCEL_REQUESTED_AT_KEY]
        .as_string()
        .is_not(None)
        .label("chain_cancel_requested")
    )
    return select(
        Analysis.id.label("id"),
        Analysis.document_id.label("document_id"),
        Analysis.skill_id.label("skill_id"),
        Analysis.skill_version.label("skill_version"),
        Analysis.provider.label("provider"),
        Analysis.model.label("model"),
        Analysis.status.label("status"),
        Analysis.verdict.label("verdict"),
        Analysis.error_message.label("error_message"),
        chain_cancel_requested,
        Analysis.created_at.label("created_at"),
        Analysis.started_at.label("started_at"),
        Analysis.completed_at.label("completed_at"),
    )


def _analysis_status_source(row) -> AnalysisStatusSource:
    return AnalysisStatusSource(
        id=row["id"],
        document_id=row["document_id"],
        skill_id=row["skill_id"],
        skill_version=row["skill_version"],
        provider=row["provider"],
        model=row["model"],
        status=row["status"],
        verdict=row["verdict"],
        error_message=row["error_message"],
        chain_cancel_requested=bool(row["chain_cancel_requested"]),
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


def _latest_run_status_summaries(*, db: Session, model, analysis_ids: list[UUID]) -> dict[UUID, RunStatusSummaryRead]:
    ranked = (
        select(
            model.id.label("id"),
            model.analysis_id.label("analysis_id"),
            model.status.label("status"),
            model.error_message.label("error_message"),
            model.created_at.label("created_at"),
            model.started_at.label("started_at"),
            model.completed_at.label("completed_at"),
            func.row_number()
            .over(
                partition_by=model.analysis_id,
                order_by=(model.created_at.desc(), model.id.desc()),
            )
            .label("status_rank"),
        )
        .where(model.analysis_id.in_(analysis_ids))
        .subquery()
    )
    latest: dict[UUID, RunStatusSummaryRead] = {}
    for row in db.execute(select(ranked).where(ranked.c.status_rank == 1)).mappings().all():
        analysis_id = row["analysis_id"]
        latest[analysis_id] = RunStatusSummaryRead(
            id=row["id"],
            status=row["status"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )
    return latest


def _latest_ic_review_status_summaries(
    *,
    db: Session,
    analysis_ids: list[UUID],
) -> dict[UUID, AnalysisCheckRunStatusRead]:
    ranked = (
        select(
            AnalysisCheckRun.id.label("id"),
            AnalysisCheckRun.analysis_id.label("analysis_id"),
            AnalysisCheckRun.status.label("status"),
            AnalysisCheckRun.current_stage.label("current_stage"),
            AnalysisCheckRun.error_message.label("error_message"),
            AnalysisCheckRun.created_at.label("created_at"),
            AnalysisCheckRun.started_at.label("started_at"),
            AnalysisCheckRun.completed_at.label("completed_at"),
            func.row_number()
            .over(
                partition_by=AnalysisCheckRun.analysis_id,
                order_by=(AnalysisCheckRun.created_at.desc(), AnalysisCheckRun.id.desc()),
            )
            .label("status_rank"),
        )
        .where(
            AnalysisCheckRun.analysis_id.in_(analysis_ids),
            AnalysisCheckRun.check_type == "ic_agentic_review",
        )
        .subquery()
    )
    latest_rows = {
        row["analysis_id"]: dict(row)
        for row in db.execute(select(ranked).where(ranked.c.status_rank == 1)).mappings().all()
    }

    run_ids = [row["id"] for row in latest_rows.values()]
    steps_by_run_id: dict[UUID, list[AnalysisCheckStepStatusRead]] = {run_id: [] for run_id in run_ids}
    if run_ids:
        steps_statement = (
            select(
                AnalysisCheckStep.id,
                AnalysisCheckStep.check_run_id,
                AnalysisCheckStep.step_name,
                AnalysisCheckStep.status,
                AnalysisCheckStep.error_message,
                AnalysisCheckStep.created_at,
                AnalysisCheckStep.started_at,
                AnalysisCheckStep.completed_at,
            )
            .where(AnalysisCheckStep.check_run_id.in_(run_ids))
            .order_by(AnalysisCheckStep.created_at, AnalysisCheckStep.id)
        )
        for row in db.execute(steps_statement).mappings().all():
            steps_by_run_id[row["check_run_id"]].append(
                AnalysisCheckStepStatusRead(
                    id=row["id"],
                    step_name=row["step_name"],
                    status=row["status"],
                    error_message=row["error_message"],
                    created_at=row["created_at"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                )
            )

    return {
        analysis_id: AnalysisCheckRunStatusRead(
            id=row["id"],
            status=row["status"],
            current_stage=row["current_stage"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            steps=steps_by_run_id.get(row["id"], []),
        )
        for analysis_id, row in latest_rows.items()
    }


def _analysis_source_traces(*, db: Session, analysis_ids: list[UUID]) -> dict[UUID, SourceTrace]:
    statement = (
        select(
            SkillSourceSnapshot.id,
            SkillSourceSnapshot.analysis_id,
            SkillSourceSnapshot.source_slug,
            SkillSourceSnapshot.resolved_revision,
            SkillSourceSnapshot.source_fingerprint,
            SkillSourceSnapshot.snapshot_mode,
            SkillSourceSnapshot.is_dirty,
            SkillSourceSnapshot.created_at,
        )
        .where(SkillSourceSnapshot.analysis_id.in_(analysis_ids))
        .order_by(SkillSourceSnapshot.analysis_id, SkillSourceSnapshot.created_at.desc())
    )
    traces: dict[UUID, SourceTrace] = {}
    for row in db.execute(statement).mappings().all():
        analysis_id = row["analysis_id"]
        if analysis_id in traces:
            continue
        traces[analysis_id] = SourceTrace(
            source_snapshot_id=row["id"],
            source_slug=row["source_slug"],
            source_revision=row["resolved_revision"],
            source_fingerprint=row["source_fingerprint"],
            snapshot_mode=row["snapshot_mode"],
            is_dirty=row["is_dirty"],
        )
    return traces


def delete_analysis_for_actor(*, db: Session, actor: User, analysis_id: UUID) -> None:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or analysis.deleted_at is not None or not can_delete_analysis(actor, analysis):
        raise AnalysisNotFoundError("Analysis not found")
    context = _analysis_deletion_context(db=db, analysis=analysis)
    _ensure_deletable_analysis_chain(context)
    _delete_analysis_result(db=db, actor=actor, context=context, deleted_at=utc_now())
    db.commit()


def delete_document_analysis_results_for_actor(*, db: Session, actor: User, document_id: UUID) -> None:
    document = get_document_for_actor(db=db, actor=actor, document_id=document_id)
    analyses = list(
        db.execute(
            select(Analysis)
            .where(Analysis.document_id == document.id, Analysis.deleted_at.is_(None))
            .order_by(Analysis.created_at.desc())
        )
        .scalars()
        .all()
    )
    forbidden = [analysis for analysis in analyses if not can_delete_analysis(actor, analysis)]
    if forbidden:
        raise AnalysisNotFoundError("Analysis not found")

    contexts = [_analysis_deletion_context(db=db, analysis=analysis) for analysis in analyses]
    for context in contexts:
        _ensure_deletable_analysis_chain(context)

    deleted_at = utc_now()
    for context in contexts:
        _delete_analysis_result(db=db, actor=actor, context=context, deleted_at=deleted_at)

    record_audit(
        db=db,
        actor_id=actor.id,
        action="document.analysis_results_deleted",
        entity_type="document",
        entity_id=document.id,
        metadata={
            "analysis_count": len(analyses),
        },
    )
    db.commit()


def _analysis_deletion_context(*, db: Session, analysis: Analysis) -> AnalysisDeletionContext:
    predicted_runs = _analysis_predicted_comment_runs(db=db, analysis_id=analysis.id)
    detail_runs = _analysis_detail_runs(db=db, analysis_id=analysis.id)
    check_runs = _analysis_check_runs(db=db, analysis_id=analysis.id)
    check_steps = [
        step
        for check_run in check_runs
        for step in _analysis_check_steps(db=db, check_run_id=check_run.id)
    ]
    return AnalysisDeletionContext(
        analysis=analysis,
        predicted_runs=predicted_runs,
        detail_runs=detail_runs,
        check_runs=check_runs,
        check_steps=check_steps,
    )


def _ensure_deletable_analysis_chain(context: AnalysisDeletionContext) -> None:
    if _analysis_chain_has_active_runs(
        analysis=context.analysis,
        predicted_runs=context.predicted_runs,
        detail_runs=context.detail_runs,
        check_runs=context.check_runs,
        check_steps=context.check_steps,
    ):
        raise AnalysisPreconditionError("Cannot delete analysis results while analysis is running")


def _delete_analysis_result(*, db: Session, actor: User, context: AnalysisDeletionContext, deleted_at) -> None:
    analysis = context.analysis
    predicted_runs = context.predicted_runs
    detail_runs = context.detail_runs
    check_runs = context.check_runs
    check_steps = context.check_steps
    storage = LocalDocumentStorage(get_settings().storage_root)
    deleted_storage_paths = _delete_analysis_storage_artifacts(
        db=db,
        storage=storage,
        analysis=analysis,
        predicted_runs=predicted_runs,
        detail_runs=detail_runs,
        check_runs=check_runs,
        check_steps=check_steps,
    )

    predicted_run_ids = [run.id for run in predicted_runs]
    check_run_ids = [run.id for run in check_runs]
    if predicted_run_ids:
        db.execute(delete(RetrievalSnapshot).where(RetrievalSnapshot.predicted_comment_run_id.in_(predicted_run_ids)))
        db.execute(
            delete(SkillSourceSnapshot).where(SkillSourceSnapshot.predicted_comment_run_id.in_(predicted_run_ids))
        )
        db.execute(delete(PredictedCommentRun).where(PredictedCommentRun.id.in_(predicted_run_ids)))
    if check_run_ids:
        db.execute(delete(SkillSourceSnapshot).where(SkillSourceSnapshot.analysis_check_run_id.in_(check_run_ids)))
        db.execute(delete(AnalysisCheckStep).where(AnalysisCheckStep.check_run_id.in_(check_run_ids)))
        db.execute(delete(AnalysisCheckRun).where(AnalysisCheckRun.id.in_(check_run_ids)))

    db.execute(delete(SkillSourceSnapshot).where(SkillSourceSnapshot.analysis_id == analysis.id))
    db.execute(delete(AnalysisDetailRun).where(AnalysisDetailRun.analysis_id == analysis.id))

    previous_status = analysis.status
    has_feedback = db.execute(select(Feedback.id).where(Feedback.analysis_id == analysis.id).limit(1)).first() is not None
    analysis.deleted_at = deleted_at
    if has_feedback:
        analysis.run_parameters = {
            **(analysis.run_parameters or {}),
            "deleted_at": deleted_at.isoformat(),
            "deleted_by_user_id": str(actor.id),
            "deleted_result_trace_preserved_for_feedback": True,
        }
    else:
        analysis.verdict = None
        analysis.summary = None
        analysis.structured_output = None
        analysis.raw_output = None
        analysis.error_message = None
        analysis.latency_ms = None
        analysis.input_tokens = None
        analysis.output_tokens = None
        analysis.estimated_cost = None
        analysis.run_parameters = {
            "deleted_at": deleted_at.isoformat(),
            "deleted_by_user_id": str(actor.id),
        }
    record_audit(
        db=db,
        actor_id=actor.id,
        action="analysis.deleted",
        entity_type="analysis",
        entity_id=analysis.id,
        metadata={
            "document_id": str(analysis.document_id),
            "previous_status": previous_status,
            "storage_paths_deleted_count": len(deleted_storage_paths),
            "predicted_comment_runs_deleted": len(predicted_runs),
            "analysis_detail_runs_deleted": len(detail_runs),
            "analysis_check_runs_deleted": len(check_runs),
            "result_trace_preserved_for_feedback": has_feedback,
        },
    )


def _analysis_chain_has_active_runs(
    *,
    analysis: Analysis,
    predicted_runs: list[PredictedCommentRun],
    detail_runs: list[AnalysisDetailRun],
    check_runs: list[AnalysisCheckRun],
    check_steps: list[AnalysisCheckStep],
) -> bool:
    if analysis.status in ACTIVE_RUN_STATUSES:
        return True
    return any(run.status in ACTIVE_RUN_STATUSES for run in [*predicted_runs, *detail_runs, *check_runs, *check_steps])


def _delete_analysis_storage_artifacts(
    *,
    db: Session,
    storage: LocalDocumentStorage,
    analysis: Analysis,
    predicted_runs: list[PredictedCommentRun],
    detail_runs: list[AnalysisDetailRun],
    check_runs: list[AnalysisCheckRun],
    check_steps: list[AnalysisCheckStep],
) -> list[str]:
    paths: set[str] = set()
    run_ids = [analysis.id]
    run_ids.extend(run.id for run in predicted_runs)
    run_ids.extend(run.id for run in detail_runs)
    run_ids.extend(step.id for step in check_steps)

    for run_id in run_ids:
        storage.delete_rendered_prompt_dir(run_id=run_id)

    storage.delete_ic_review_analysis_dir(analysis_id=analysis.id)

    check_runs_by_id = {run.id: run for run in check_runs}
    for run in check_runs:
        paths.update(
            _safe_ic_review_artifact_paths(
                storage=storage,
                analysis_id=analysis.id,
                run_id=run.id,
                raw_paths=[
                    *_artifact_paths_from_items(run.artifacts),
                    *_artifact_paths_from_metadata(run.uploaded_workbook_metadata),
                ],
            )
        )
    for step in check_steps:
        check_run = check_runs_by_id.get(step.check_run_id)
        if check_run is None:
            continue
        step_paths: set[str] = set()
        if step.prompt_artifact_path:
            step_paths.add(step.prompt_artifact_path)
        step_paths.update(_artifact_paths_from_items(step.artifacts))
        paths.update(
            _safe_ic_review_artifact_paths(
                storage=storage,
                analysis_id=analysis.id,
                run_id=check_run.id,
                raw_paths=step_paths,
            )
        )

    predicted_run_ids = [run.id for run in predicted_runs]
    check_run_ids = [run.id for run in check_runs]
    snapshot_rows = list(
        db.execute(select(SkillSourceSnapshot).where(SkillSourceSnapshot.analysis_id == analysis.id)).scalars().all()
    )
    if predicted_run_ids:
        snapshot_rows.extend(
            db.execute(
                select(SkillSourceSnapshot).where(SkillSourceSnapshot.predicted_comment_run_id.in_(predicted_run_ids))
            )
            .scalars()
            .all()
        )
    if check_run_ids:
        snapshot_rows.extend(
            db.execute(
                select(SkillSourceSnapshot).where(SkillSourceSnapshot.analysis_check_run_id.in_(check_run_ids))
            )
            .scalars()
            .all()
        )
    for snapshot in snapshot_rows:
        paths.add(snapshot.artifact_path)
    if predicted_run_ids:
        for snapshot in db.execute(
            select(RetrievalSnapshot).where(RetrievalSnapshot.predicted_comment_run_id.in_(predicted_run_ids))
        ).scalars():
            paths.add(snapshot.artifact_path)

    deleted_paths: list[str] = []
    for path in sorted(paths):
        try:
            storage.delete_stored_path(path)
        except (FileNotFoundError, ValueError):
            continue
        deleted_paths.append(path)
    return deleted_paths


def _artifact_paths_from_parameters(parameters: dict | None) -> set[str]:
    if not isinstance(parameters, dict):
        return set()
    paths: set[str] = set()
    for key in (
        "rendered_prompt_artifact_path",
        "source_snapshot_artifact_path",
        "retrieval_snapshot_artifact_path",
        "context_pack_artifact_path",
        "synthesis_prompt_artifact_path",
        "prompt_artifact_path",
        "artifact_path",
    ):
        value = parameters.get(key)
        if isinstance(value, str) and value:
            paths.add(value)
    for key in ("skill_source_snapshot", "retrieval_snapshot"):
        value = parameters.get(key)
        if isinstance(value, dict):
            paths.update(_artifact_paths_from_parameters(value))
    return paths


def _artifact_paths_from_items(items: list | None) -> set[str]:
    if not isinstance(items, list):
        return set()
    paths: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            paths.update(_artifact_paths_from_parameters(item))
            value = item.get("path")
            if isinstance(value, str) and value:
                paths.add(value)
    return paths


def _artifact_paths_from_metadata(metadata: dict | None) -> set[str]:
    if not isinstance(metadata, dict):
        return set()
    paths = _artifact_paths_from_parameters(metadata)
    value = metadata.get("storage_path")
    if isinstance(value, str) and value:
        paths.add(value)
    return paths


def _safe_ic_review_artifact_paths(
    *,
    storage: LocalDocumentStorage,
    analysis_id: UUID,
    run_id: UUID,
    raw_paths: set[str] | list[str],
) -> set[str]:
    run_dir = storage.ic_review_run_dir(analysis_id=analysis_id, run_id=run_id)
    paths: set[str] = set()
    for raw_path in raw_paths:
        try:
            path = storage.stored_path(raw_path)
        except ValueError:
            continue
        if path.is_relative_to(run_dir):
            paths.add(str(path))
    return paths


def cancel_analysis_for_actor(*, db: Session, actor: User, analysis_id: UUID) -> Analysis:
    analysis = get_analysis_for_actor(db=db, actor=actor, analysis_id=analysis_id)
    cancelled_at = utc_now()
    cancelled_any = False
    predicted_runs = _analysis_predicted_comment_runs(db=db, analysis_id=analysis.id)
    detail_runs = _analysis_detail_runs(db=db, analysis_id=analysis.id)
    check_runs = _analysis_check_runs(db=db, analysis_id=analysis.id)

    if not _full_analysis_chain_completed(analysis=analysis, predicted_runs=predicted_runs, check_runs=check_runs):
        run_parameters = dict(analysis.run_parameters or {})
        if ANALYSIS_CHAIN_CANCEL_REQUESTED_AT_KEY not in run_parameters:
            run_parameters[ANALYSIS_CHAIN_CANCEL_REQUESTED_AT_KEY] = cancelled_at.isoformat()
            run_parameters[ANALYSIS_CHAIN_CANCELLED_BY_USER_ID_KEY] = str(actor.id)
            analysis.run_parameters = run_parameters
            flag_modified(analysis, "run_parameters")
            cancelled_any = True

    if analysis.status in ACTIVE_RUN_STATUSES:
        analysis.status = RunStatus.CANCELLED.value
        analysis.error_message = "cancelled_by_user"
        analysis.completed_at = cancelled_at
        cancelled_any = True

    for predicted_run in predicted_runs:
        if predicted_run.status in ACTIVE_RUN_STATUSES:
            predicted_run.status = RunStatus.CANCELLED.value
            predicted_run.error_message = "cancelled_by_user"
            predicted_run.completed_at = cancelled_at
            cancelled_any = True

    for detail_run in detail_runs:
        if detail_run.status in ACTIVE_RUN_STATUSES:
            detail_run.status = RunStatus.CANCELLED.value
            detail_run.error_message = "cancelled_by_user"
            detail_run.completed_at = cancelled_at
            cancelled_any = True

    for check_run in check_runs:
        if check_run.status in ACTIVE_RUN_STATUSES:
            check_run.status = RunStatus.CANCELLED.value
            check_run.current_stage = "cancelled"
            check_run.error_message = "cancelled_by_user"
            check_run.completed_at = cancelled_at
            for step in _analysis_check_steps(db=db, check_run_id=check_run.id):
                if step.status in ACTIVE_RUN_STATUSES:
                    step.status = RunStatus.CANCELLED.value
                    step.error_message = "cancelled_by_user"
                    step.completed_at = cancelled_at
            cancelled_any = True

    if cancelled_any:
        record_audit(
            db=db,
            actor_id=actor.id,
            action="analysis.cancelled",
            entity_type="analysis",
            entity_id=analysis.id,
            metadata={"document_id": str(analysis.document_id)},
        )
        db.commit()
        db.refresh(analysis)

    return analysis


def read_analysis(*, db: Session, actor: User, analysis: Analysis) -> AnalysisRead:
    skill = db.get(Skill, analysis.skill_id)
    predicted_run = _latest_predicted_comment_run(db=db, analysis_id=analysis.id)
    detail_run = latest_analysis_detail_run(db=db, analysis_id=analysis.id)
    ic_review_run = _latest_ic_review_run_read(db=db, actor=actor, analysis_id=analysis.id)
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
        run_parameters=_sanitize_model_anonymization_parameters(analysis.run_parameters),
        source_trace=_source_trace(analysis.run_parameters),
        created_at=analysis.created_at,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
        predicted_comment_run=(
            _read_predicted_comment_run(db=db, actor=actor, predicted_run=predicted_run) if predicted_run else None
        ),
        detail_run=_read_analysis_detail_run(actor=actor, detail_run=detail_run) if detail_run else None,
        ic_review_run=ic_review_run,
    )


def request_analysis_detail_run(*, db: Session, actor: User, analysis_id: UUID) -> AnalysisDetailRun:
    analysis = get_analysis_for_actor(db=db, actor=actor, analysis_id=analysis_id)
    if analysis.status != RunStatus.COMPLETED.value:
        raise AnalysisPreconditionError("Analysis is not completed")
    previous_response_id = (analysis.run_parameters or {}).get("gate_challenger_response_id")

    reusable_run = reusable_analysis_detail_run(db=db, analysis_id=analysis.id)
    if reusable_run is not None:
        reusable_run.created_for_request = False
        return reusable_run

    run_parameters = {
        "previous_response_id": previous_response_id,
        "output_language": (analysis.run_parameters or {}).get("output_language", "ru"),
        "source_snapshot_id": (analysis.run_parameters or {}).get("source_snapshot_id"),
        "source_fingerprint": (analysis.run_parameters or {}).get("source_fingerprint"),
        "source_revision": (analysis.run_parameters or {}).get("source_revision"),
        "skill_source_snapshot": (analysis.run_parameters or {}).get("skill_source_snapshot"),
    }
    if previous_response_id:
        run_parameters["provider_api"] = "responses"
    else:
        run_parameters["provider_api"] = "chat_completions_fallback"
        run_parameters["fallback_reason"] = "gate_challenger_response_id_missing"
    detail_run = AnalysisDetailRun(
        analysis_id=analysis.id,
        status=RunStatus.QUEUED.value,
        provider=analysis.provider,
        model=analysis.model,
        previous_response_id=str(previous_response_id) if previous_response_id else None,
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


def _analysis_predicted_comment_runs(*, db: Session, analysis_id: UUID) -> list[PredictedCommentRun]:
    statement = select(PredictedCommentRun).where(PredictedCommentRun.analysis_id == analysis_id)
    return list(db.execute(statement).scalars().all())


def _analysis_detail_runs(*, db: Session, analysis_id: UUID) -> list[AnalysisDetailRun]:
    statement = select(AnalysisDetailRun).where(AnalysisDetailRun.analysis_id == analysis_id)
    return list(db.execute(statement).scalars().all())


def _analysis_check_runs(*, db: Session, analysis_id: UUID) -> list[AnalysisCheckRun]:
    statement = select(AnalysisCheckRun).where(AnalysisCheckRun.analysis_id == analysis_id)
    return list(db.execute(statement).scalars().all())


def _analysis_check_steps(*, db: Session, check_run_id: UUID) -> list[AnalysisCheckStep]:
    statement = select(AnalysisCheckStep).where(AnalysisCheckStep.check_run_id == check_run_id)
    return list(db.execute(statement).scalars().all())


def _full_analysis_chain_completed(
    *,
    analysis: Analysis,
    predicted_runs: list[PredictedCommentRun],
    check_runs: list[AnalysisCheckRun],
) -> bool:
    latest_predicted_run = max(predicted_runs, key=lambda run: run.created_at, default=None)
    ic_review_runs = [run for run in check_runs if run.check_type == "ic_agentic_review"]
    latest_ic_review_run = max(ic_review_runs, key=lambda run: (run.created_at, str(run.id)), default=None)
    return (
        analysis.status == RunStatus.COMPLETED.value
        and latest_predicted_run is not None
        and latest_predicted_run.status == RunStatus.COMPLETED.value
        and latest_ic_review_run is not None
        and latest_ic_review_run.status == RunStatus.COMPLETED.value
    )


def _latest_ic_review_run_read(*, db: Session, actor: User, analysis_id: UUID):
    from app.services.ic_review import IC_REVIEW_CHECK_TYPE, read_ic_review_run

    statement = (
        select(AnalysisCheckRun)
        .where(AnalysisCheckRun.analysis_id == analysis_id, AnalysisCheckRun.check_type == IC_REVIEW_CHECK_TYPE)
        .order_by(AnalysisCheckRun.created_at.desc(), AnalysisCheckRun.id.desc())
    )
    run = db.execute(statement).scalars().first()
    return read_ic_review_run(db=db, actor=actor, run=run) if run else None


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
        run_parameters=_sanitize_model_anonymization_parameters(predicted_run.run_parameters),
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
        run_parameters=_sanitize_model_anonymization_parameters(detail_run.run_parameters),
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


def _sanitize_model_anonymization_parameters(run_parameters: dict | None) -> dict:
    parameters = dict(run_parameters or {})
    metadata = parameters.get(MODEL_ANONYMIZATION_RUN_PARAMETER_KEY)
    if isinstance(metadata, dict) and "replacements" in metadata:
        safe_metadata = dict(metadata)
        safe_metadata.pop("replacements", None)
        parameters[MODEL_ANONYMIZATION_RUN_PARAMETER_KEY] = safe_metadata
    return parameters


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

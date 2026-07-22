from pathlib import Path
from uuid import UUID
import zipfile

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authz.policies import can_read_raw_output
from app.core.config import default_skill_source_snapshot_mode, get_settings
from app.models.analysis import Analysis, AnalysisCheckRun, AnalysisCheckStep
from app.models.document import Document
from app.models.skill import Skill
from app.models.skill_source import SkillSource
from app.models.user import User
from app.schemas.analyses import AnalysisCheckRunRead, AnalysisCheckStepRead, SourceTrace
from app.schemas.enums import EntityStatus, Provider, RunStatus, SkillType
from app.schemas.provider_settings import normalize_available_models
from app.services.analyses import AnalysisNotFoundError, AnalysisPreconditionError, get_analysis_for_actor
from app.services.external_sources import SourceUnavailableError
from app.services.provider_keys import get_shared_provider_key
from app.services.skill_snapshots import create_skill_source_snapshot
from app.services.skills import skill_source_snapshot
from app.storage.local import LocalDocumentStorage, StoredFileTooLargeError


IC_REVIEW_CHECK_TYPE = "ic_agentic_review"
IC_REVIEW_SKILL_NAME = "ic_agentic_review"
MAX_WORKBOOK_SIZE_BYTES = 25 * 1024 * 1024


class IcReviewRunNotFoundError(ValueError):
    pass


class UnsupportedWorkbookFileTypeError(ValueError):
    pass


class IcReviewWorkbookTooLargeError(ValueError):
    pass


def create_ic_review_run_for_analysis(
    *,
    db: Session,
    actor: User,
    analysis_id: UUID,
    provider: Provider,
    model: str,
    output_language: str,
    financial_model: UploadFile | None,
) -> AnalysisCheckRun:
    analysis = get_analysis_for_actor(db=db, actor=actor, analysis_id=analysis_id)
    if analysis.status != RunStatus.COMPLETED.value:
        raise AnalysisPreconditionError("Analysis is not completed")

    _validate_provider_model(db=db, provider=provider, model=model)
    skill = _resolve_ic_review_skill(db=db)
    run = AnalysisCheckRun(
        analysis_id=analysis.id,
        skill_id=skill.id,
        skill_version=skill.version,
        check_type=IC_REVIEW_CHECK_TYPE,
        provider=provider.value,
        model=model,
        status=RunStatus.QUEUED.value,
        current_stage="queued",
        run_parameters={},
        artifacts=[],
        uploaded_workbook_metadata={},
    )
    db.add(run)
    db.flush()

    workbook_metadata: dict = {}
    spreadsheet_mode = "not_provided"
    if financial_model is not None:
        workbook_metadata = _save_workbook(
            analysis_id=analysis.id,
            run_id=run.id,
            upload=financial_model,
        )
        spreadsheet_mode = "uploaded"

    run.uploaded_workbook_metadata = workbook_metadata
    run_parameters = {
        "output_language": output_language,
        "spreadsheet_mode": spreadsheet_mode,
        "skill_source_snapshot": skill_source_snapshot(skill),
    }
    try:
        _attach_source_snapshot(db=db, run=run, skill=skill, run_parameters=run_parameters)
    except Exception:
        _cleanup_run_storage(analysis_id=analysis.id, run_id=run.id)
        raise
    run.run_parameters = run_parameters
    db.commit()
    db.refresh(run)
    return run


def create_automatic_ic_review_run_for_analysis(
    *,
    db: Session,
    analysis: Analysis,
    output_language: str,
) -> AnalysisCheckRun:
    if analysis.status != RunStatus.COMPLETED.value:
        raise AnalysisPreconditionError("Analysis is not completed")

    reusable_run = _reusable_ic_review_run(db=db, analysis_id=analysis.id)
    if reusable_run is not None:
        reusable_run.created_for_request = False
        return reusable_run

    provider = Provider(analysis.provider)
    _validate_provider_model(db=db, provider=provider, model=analysis.model)
    skill = _resolve_ic_review_skill(db=db)
    run = AnalysisCheckRun(
        analysis_id=analysis.id,
        skill_id=skill.id,
        skill_version=skill.version,
        check_type=IC_REVIEW_CHECK_TYPE,
        provider=analysis.provider,
        model=analysis.model,
        status=RunStatus.QUEUED.value,
        current_stage="queued",
        run_parameters={},
        artifacts=[],
        uploaded_workbook_metadata={},
    )
    db.add(run)
    db.flush()

    workbook_metadata: dict = {}
    spreadsheet_mode = "not_provided"
    linked_fin_summary_metadata = _linked_fin_summary_metadata(db=db, analysis=analysis)
    linked_fin_summary_document = linked_fin_summary_metadata.pop("_document", None)
    if linked_fin_summary_document is not None:
        linked_fin_summary_metadata["usage"] = "attached"
        if Path(linked_fin_summary_document.original_filename).suffix.lower() == ".xlsx":
            try:
                workbook_metadata = _save_workbook_from_document(
                    analysis_id=analysis.id,
                    run_id=run.id,
                    document=linked_fin_summary_document,
                )
                spreadsheet_mode = "uploaded"
                linked_fin_summary_metadata["usage"] = "workbook_uploaded"
            except (OSError, UnsupportedWorkbookFileTypeError, IcReviewWorkbookTooLargeError) as exc:
                linked_fin_summary_metadata["usage"] = "ignored_invalid_xlsx"
                linked_fin_summary_metadata["error"] = exc.__class__.__name__
        else:
            linked_fin_summary_metadata["usage"] = "ignored_non_xlsx"

    run.uploaded_workbook_metadata = workbook_metadata
    run_parameters = {
        "output_language": output_language,
        "spreadsheet_mode": spreadsheet_mode,
        "launch_mode": "automatic_full_analysis",
        "skill_source_snapshot": skill_source_snapshot(skill),
    }
    if linked_fin_summary_metadata:
        run_parameters["linked_fin_summary_document"] = linked_fin_summary_metadata
    try:
        _attach_source_snapshot(db=db, run=run, skill=skill, run_parameters=run_parameters)
    except Exception:
        _cleanup_run_storage(analysis_id=analysis.id, run_id=run.id)
        raise
    run.run_parameters = run_parameters
    db.commit()
    db.refresh(run)
    run.created_for_request = True
    return run


def list_ic_review_runs_for_analysis(*, db: Session, actor: User, analysis_id: UUID) -> list[AnalysisCheckRun]:
    analysis = get_analysis_for_actor(db=db, actor=actor, analysis_id=analysis_id)
    statement = (
        select(AnalysisCheckRun)
        .where(AnalysisCheckRun.analysis_id == analysis.id, AnalysisCheckRun.check_type == IC_REVIEW_CHECK_TYPE)
        .order_by(AnalysisCheckRun.created_at.desc(), AnalysisCheckRun.id.desc())
    )
    return list(db.execute(statement).scalars().all())


def latest_ic_review_run_for_analysis(*, db: Session, actor: User, analysis_id: UUID) -> AnalysisCheckRun:
    runs = list_ic_review_runs_for_analysis(db=db, actor=actor, analysis_id=analysis_id)
    if not runs:
        raise IcReviewRunNotFoundError("IC review run not found")
    return runs[0]


def get_ic_review_run_for_actor(*, db: Session, actor: User, run_id: UUID) -> AnalysisCheckRun:
    run = db.get(AnalysisCheckRun, run_id)
    if run is None or run.check_type != IC_REVIEW_CHECK_TYPE:
        raise IcReviewRunNotFoundError("IC review run not found")
    try:
        get_analysis_for_actor(db=db, actor=actor, analysis_id=run.analysis_id)
    except AnalysisNotFoundError as exc:
        raise IcReviewRunNotFoundError("IC review run not found") from exc
    return run


def read_ic_review_run(*, db: Session, actor: User, run: AnalysisCheckRun) -> AnalysisCheckRunRead:
    skill = db.get(Skill, run.skill_id)
    admin = can_read_raw_output(actor, run)
    steps = _steps_for_run(db=db, run_id=run.id)
    return AnalysisCheckRunRead(
        id=run.id,
        analysis_id=run.analysis_id,
        skill_id=run.skill_id,
        skill_name=skill.name if skill else "unknown",
        skill_version=run.skill_version,
        check_type=run.check_type,
        provider=run.provider,
        model=run.model,
        status=run.status,
        current_stage=run.current_stage,
        structured_output=run.structured_output,
        legacy_output=run.legacy_output if admin else None,
        raw_output=run.raw_output if admin else None,
        error_message=run.error_message,
        latency_ms=run.latency_ms,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        estimated_cost=run.estimated_cost,
        run_parameters=_sanitize_run_parameters(run.run_parameters, include_paths=admin),
        uploaded_workbook_metadata=_sanitize_metadata(run.uploaded_workbook_metadata, include_paths=admin),
        artifacts=_sanitize_artifacts(run.artifacts, include_paths=admin),
        source_trace=_source_trace(run.run_parameters),
        steps=[_read_step(actor=actor, step=step, include_paths=admin) for step in steps],
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def artifact_path_for_actor(*, db: Session, actor: User, run_id: UUID, artifact_key: str) -> tuple[Path, str, str]:
    run = get_ic_review_run_for_actor(db=db, actor=actor, run_id=run_id)
    artifact = _find_artifact(run.artifacts, artifact_key)
    if artifact is None:
        for step in _steps_for_run(db=db, run_id=run.id):
            artifact = _find_artifact(step.artifacts, artifact_key)
            if artifact is not None:
                break
    if artifact is None or not artifact.get("path"):
        raise IcReviewRunNotFoundError("Artifact not found")
    if not _can_download_artifact(actor=actor, run=run, artifact=artifact):
        raise IcReviewRunNotFoundError("Artifact not found")

    storage = LocalDocumentStorage(get_settings().storage_root)
    try:
        path = storage.stored_path(str(artifact["path"]))
        run_dir = storage.ic_review_run_dir(analysis_id=run.analysis_id, run_id=run.id)
    except ValueError as exc:
        raise IcReviewRunNotFoundError("Artifact not found") from exc
    if not path.is_relative_to(run_dir) or not path.is_file():
        raise IcReviewRunNotFoundError("Artifact not found")
    filename = str(artifact.get("filename") or path.name)
    media_type = str(artifact.get("media_type") or "application/octet-stream")
    return path, filename, media_type


def mark_ic_review_run_enqueue_failed(*, db: Session, run_id: UUID, error_message: str) -> AnalysisCheckRun | None:
    run = db.get(AnalysisCheckRun, run_id)
    if run is None:
        return None
    run.status = RunStatus.FAILED.value
    run.current_stage = "enqueue_failed"
    run.error_message = f"Failed to enqueue IC review run: {error_message}"
    db.commit()
    db.refresh(run)
    return run


def _validate_provider_model(*, db: Session, provider: Provider, model: str) -> None:
    if provider != Provider.HERMES:
        provider_key = get_shared_provider_key(db=db, provider=provider)
        if provider_key is None:
            raise AnalysisPreconditionError("Provider key is not configured")
        available_models = normalize_available_models(provider, provider_key.available_models, provider_key.default_model)
        if model not in available_models:
            raise AnalysisPreconditionError("Selected model is not available")
    if provider == Provider.HERMES and not get_settings().hermes_enabled:
        raise AnalysisPreconditionError("Hermes provider is disabled")


def _resolve_ic_review_skill(*, db: Session) -> Skill:
    statement = select(Skill).where(
        Skill.name == IC_REVIEW_SKILL_NAME,
        Skill.skill_type == SkillType.ANALYSIS_CHECK.value,
        Skill.status == EntityStatus.ACTIVE.value,
    )
    skill = db.execute(statement.order_by(Skill.created_at.desc())).scalars().first()
    if skill is None:
        raise AnalysisPreconditionError("No active IC review skill is available")
    return skill


def _save_workbook(*, analysis_id: UUID, run_id: UUID, upload: UploadFile) -> dict:
    original_filename = upload.filename or "upload"
    if Path(original_filename).suffix != ".xlsx":
        raise UnsupportedWorkbookFileTypeError("Financial model must be a .xlsx file")
    _validate_xlsx_container(upload)
    storage = LocalDocumentStorage(get_settings().storage_root)
    try:
        stored = storage.save_ic_review_workbook(
            analysis_id=analysis_id,
            run_id=run_id,
            original_filename=original_filename,
            source=upload.file,
            max_size_bytes=MAX_WORKBOOK_SIZE_BYTES,
        )
    except StoredFileTooLargeError as exc:
        raise IcReviewWorkbookTooLargeError("File exceeds maximum upload size") from exc
    return {
        "filename": original_filename,
        "safe_filename": stored.safe_original_filename,
        "size_bytes": stored.size_bytes,
        "sha256": stored.sha256,
        "storage_path": str(stored.path),
    }


def _save_workbook_from_document(*, analysis_id: UUID, run_id: UUID, document: Document) -> dict:
    original_filename = document.original_filename or "upload.xlsx"
    source_path = Path(document.storage_path)
    with source_path.open("rb") as source:
        _validate_xlsx_stream(source)
        stored = LocalDocumentStorage(get_settings().storage_root).save_ic_review_workbook(
            analysis_id=analysis_id,
            run_id=run_id,
            original_filename=original_filename,
            source=source,
            max_size_bytes=MAX_WORKBOOK_SIZE_BYTES,
        )
    return {
        "filename": original_filename,
        "safe_filename": stored.safe_original_filename,
        "size_bytes": stored.size_bytes,
        "sha256": stored.sha256,
        "storage_path": str(stored.path),
        "source_document_id": str(document.id),
    }


def _validate_xlsx_container(upload: UploadFile) -> None:
    _validate_xlsx_stream(upload.file)


def _validate_xlsx_stream(source) -> None:
    try:
        source.seek(0)
        with zipfile.ZipFile(source) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError) as exc:
        raise UnsupportedWorkbookFileTypeError("Financial model must be a valid .xlsx file") from exc
    finally:
        source.seek(0)

    if "[Content_Types].xml" not in names or not any(name.startswith("xl/") for name in names):
        raise UnsupportedWorkbookFileTypeError("Financial model must be a valid .xlsx file")


def _linked_fin_summary_metadata(*, db: Session, analysis: Analysis) -> dict:
    document = db.get(Document, analysis.document_id)
    if document is None or document.linked_fin_summary_document_id is None:
        return {}
    linked = db.get(Document, document.linked_fin_summary_document_id)
    if linked is None:
        return {}
    return {
        "_document": linked,
        "id": str(linked.id),
        "original_filename": linked.original_filename,
        "mime_type": linked.mime_type,
        "file_size_bytes": linked.file_size_bytes,
        "parse_status": linked.parse_status,
    }


def _reusable_ic_review_run(*, db: Session, analysis_id: UUID) -> AnalysisCheckRun | None:
    statement = (
        select(AnalysisCheckRun)
        .where(
            AnalysisCheckRun.analysis_id == analysis_id,
            AnalysisCheckRun.check_type == IC_REVIEW_CHECK_TYPE,
            AnalysisCheckRun.status.in_(
                [RunStatus.QUEUED.value, RunStatus.RUNNING.value, RunStatus.COMPLETED.value]
            ),
        )
        .order_by(AnalysisCheckRun.created_at.desc(), AnalysisCheckRun.id.desc())
    )
    return db.execute(statement).scalars().first()


def _attach_source_snapshot(*, db: Session, run: AnalysisCheckRun, skill: Skill, run_parameters: dict) -> None:
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
            analysis_id=None,
            predicted_comment_run_id=None,
            analysis_check_run_id=run.id,
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


def _steps_for_run(*, db: Session, run_id: UUID) -> list[AnalysisCheckStep]:
    statement = (
        select(AnalysisCheckStep)
        .where(AnalysisCheckStep.check_run_id == run_id)
        .order_by(AnalysisCheckStep.created_at, AnalysisCheckStep.step_name)
    )
    return list(db.execute(statement).scalars().all())


def _read_step(*, actor: User, step: AnalysisCheckStep, include_paths: bool) -> AnalysisCheckStepRead:
    admin = can_read_raw_output(actor, step)
    return AnalysisCheckStepRead(
        id=step.id,
        check_run_id=step.check_run_id,
        step_type=step.step_type,
        step_name=step.step_name,
        status=step.status,
        prompt_fingerprint=step.prompt_fingerprint,
        prompt_artifact_path=step.prompt_artifact_path if include_paths else None,
        raw_output=step.raw_output if admin else None,
        structured_output=step.structured_output if admin else None,
        error_message=step.error_message,
        latency_ms=step.latency_ms,
        input_tokens=step.input_tokens,
        output_tokens=step.output_tokens,
        estimated_cost=step.estimated_cost,
        artifacts=_sanitize_artifacts(step.artifacts, include_paths=include_paths),
        created_at=step.created_at,
        started_at=step.started_at,
        completed_at=step.completed_at,
    )


def _sanitize_artifacts(artifacts: list | None, *, include_paths: bool) -> list[dict]:
    sanitized = []
    for artifact in artifacts or []:
        if not isinstance(artifact, dict):
            continue
        item = dict(artifact)
        if not include_paths:
            item.pop("path", None)
        sanitized.append(item)
    return sanitized


def _sanitize_metadata(metadata: dict | None, *, include_paths: bool) -> dict:
    item = dict(metadata or {})
    if not include_paths:
        item.pop("storage_path", None)
        item.pop("path", None)
    return item


def _sanitize_run_parameters(run_parameters: dict | None, *, include_paths: bool) -> dict:
    parameters = dict(run_parameters or {})
    if include_paths:
        return parameters
    return _strip_path_values(parameters)


def _strip_path_values(value):
    if isinstance(value, dict):
        stripped = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key == "path" or normalized_key.endswith("_path") or normalized_key.endswith("_artifact_path"):
                continue
            stripped[key] = _strip_path_values(item)
        return stripped
    if isinstance(value, list):
        return [_strip_path_values(item) for item in value]
    return value


def _can_download_artifact(*, actor: User, run: AnalysisCheckRun, artifact: dict) -> bool:
    if can_read_raw_output(actor, run):
        return True
    return artifact.get("visibility") == "user" or artifact.get("user_visible") is True


def _cleanup_run_storage(*, analysis_id: UUID, run_id: UUID) -> None:
    storage = LocalDocumentStorage(get_settings().storage_root)
    storage.delete_ic_review_run_dir(analysis_id=analysis_id, run_id=run_id)


def _find_artifact(artifacts: list | None, artifact_key: str) -> dict | None:
    for artifact in artifacts or []:
        if isinstance(artifact, dict) and artifact.get("key") == artifact_key:
            return artifact
    return None


def _source_trace(run_parameters: dict | None) -> SourceTrace | None:
    parameters = run_parameters or {}
    snapshot = parameters.get("skill_source_snapshot") or {}
    snapshot_id = parameters.get("source_snapshot_id") or snapshot.get("id")
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
    )

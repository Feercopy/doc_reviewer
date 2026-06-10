import hashlib
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.core.config import get_settings
from app.logging import worker_logger
from app.models.analysis import Analysis, PredictedCommentRun
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.models.skill import Skill
from app.models.skill_source import SkillSource
from app.models.base import utc_now
from app.schemas.enums import EntityStatus, Provider, RunStatus, SkillSourceType, SkillType
from app.security.secrets import decrypt_secret
from app.services.audit import record_audit
from app.services.devils_retrieval import create_devils_retrieval_snapshot
from app.services.skill_snapshots import create_skill_source_snapshot
from app.services.skill_sources import SkillSourceValidationError, refresh_skill_source_material
from app.services.skills import skill_source_snapshot
from app.storage.local import LocalDocumentStorage
from jobs.run_predicted_comments import run_predicted_comments
from providers.base import ProviderRunRequest
from providers.registry import get_provider_adapter
from results.schema_validation import parse_and_validate_json_output
from skills.prompt_renderer import render_prompt


DEFAULT_PREDICTED_COMMENTS_MAX_OUTPUT_TOKENS = 20000


def run_analysis(analysis_id: str, *, db: Session | None = None, enqueue_predicted_comments=None) -> None:
    owns_session = db is None
    session = db or SessionLocal()
    analysis_uuid = UUID(str(analysis_id))
    provider_raw_output = None
    provider_structured_text = None
    try:
        worker_logger.info(
            "worker_job_started",
            extra={"job_type": "run_analysis", "entity_id": str(analysis_uuid), "status": "running"},
        )
        analysis = session.get(Analysis, analysis_uuid)
        if analysis is None:
            raise ValueError(f"Analysis {analysis_id} not found")
        analysis.status = RunStatus.RUNNING.value
        analysis.started_at = utc_now()
        analysis.error_message = None
        session.commit()

        document = session.get(Document, analysis.document_id)
        skill = session.get(Skill, analysis.skill_id)
        if document is None or skill is None:
            raise RuntimeError("analysis_context_missing")
        _validate_skill_source_available(skill=skill, snapshot=analysis.run_parameters.get("skill_source_snapshot"))

        provider = Provider(analysis.provider)
        provider_key = _get_provider_key(session, analysis, provider)
        if provider != Provider.HERMES and provider_key is None:
            raise RuntimeError("provider_key_missing")
        api_key = decrypt_secret(provider_key.encrypted_api_key) if provider_key else None

        _run_devils_advocate_prepass(session=session, analysis=analysis, document=document)

        schema = json.loads(_resolve_schema_path(skill.result_schema_path).read_text(encoding="utf-8"))
        prompt = _render_and_persist_prompt(session=session, analysis=analysis, document=document, skill=skill, schema=schema)
        request = ProviderRunRequest(
            provider=provider,
            model=analysis.model,
            api_key=api_key,
            base_url=provider_key.base_url if provider_key else None,
            prompt=prompt,
            response_schema=schema,
            run_parameters=analysis.run_parameters,
        )
        result = get_provider_adapter(provider, analysis.run_parameters).run(request)
        provider_raw_output = result.raw_output
        provider_structured_text = result.structured_text
        structured = parse_and_validate_json_output(
            structured_text=result.structured_text,
            schema_path=skill.result_schema_path,
        )

        analysis.structured_output = structured
        analysis.raw_output = result.raw_output
        analysis.verdict = structured.get("verdict")
        analysis.summary = structured.get("summary")
        analysis.input_tokens = result.input_tokens
        analysis.output_tokens = result.output_tokens
        analysis.latency_ms = result.latency_ms
        analysis.estimated_cost = result.estimated_cost
        analysis.status = RunStatus.COMPLETED.value
        analysis.completed_at = utc_now()
        record_audit(
            db=session,
            actor_id=analysis.user_id,
            action="analysis.completed",
            entity_type="analysis",
            entity_id=analysis.id,
            metadata={
                "document_id": str(analysis.document_id),
                "provider": analysis.provider,
                "model": analysis.model,
                "input_tokens": analysis.input_tokens,
                "output_tokens": analysis.output_tokens,
            },
        )
        session.commit()
        worker_logger.info(
            "worker_job_completed",
            extra={"job_type": "run_analysis", "entity_id": str(analysis_uuid), "status": "completed"},
        )
    except Exception as exc:
        session.rollback()
        failed = session.get(Analysis, analysis_uuid)
        if failed is None:
            raise
        failed.status = RunStatus.FAILED.value
        failed.error_message = str(exc)
        if provider_raw_output is not None and failed.raw_output is None:
            failed.raw_output = provider_raw_output or provider_structured_text
        failed.completed_at = utc_now()
        record_audit(
            db=session,
            actor_id=failed.user_id,
            action="analysis.failed",
            entity_type="analysis",
            entity_id=failed.id,
            metadata={
                "document_id": str(failed.document_id),
                "provider": failed.provider,
                "model": failed.model,
                "error_class": exc.__class__.__name__,
            },
        )
        session.commit()
        worker_logger.info(
            "worker_job_failed",
            extra={
                "job_type": "run_analysis",
                "entity_id": str(analysis_uuid),
                "status": "failed",
                "error_class": exc.__class__.__name__,
            },
        )
    finally:
        if owns_session:
            session.close()


def _get_provider_key(session: Session, analysis: Analysis, provider: Provider) -> ProviderKey | None:
    statement = select(ProviderKey).where(
        ProviderKey.owner_id == analysis.user_id,
        ProviderKey.provider == provider.value,
    )
    return session.execute(statement).scalar_one_or_none()


def _resolve_schema_path(schema_path: str) -> Path:
    return Path(__file__).resolve().parents[3] / schema_path


def _render_and_persist_prompt(
    *,
    session: Session,
    analysis: Analysis,
    document: Document,
    skill: Skill,
    schema: dict,
) -> str:
    prompt = render_prompt(
        document=document,
        skill=skill,
        response_schema=schema,
        run_parameters=analysis.run_parameters,
    )
    storage = LocalDocumentStorage(get_settings().storage_root)
    prompt_path = storage.save_rendered_prompt(analysis_id=analysis.id, prompt=prompt)
    run_parameters = dict(analysis.run_parameters or {})
    run_parameters["rendered_prompt_artifact_path"] = str(prompt_path)
    run_parameters["prompt_fingerprint"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    analysis.run_parameters = run_parameters
    flag_modified(analysis, "run_parameters")
    session.commit()
    return prompt


def _run_devils_advocate_prepass(*, session: Session, analysis: Analysis, document: Document) -> None:
    predicted_run = _create_devils_advocate_prepass_run(session=session, analysis=analysis, document=document)
    if predicted_run is None:
        return

    run_predicted_comments(str(predicted_run.id), db=session)
    refreshed_run = session.get(PredictedCommentRun, predicted_run.id)
    if refreshed_run is None or refreshed_run.status != RunStatus.COMPLETED.value:
        return

    layer_4_context = _build_gate_challenger_layer_4_context(refreshed_run)
    if layer_4_context is None:
        return

    run_parameters = dict(analysis.run_parameters or {})
    run_parameters["gate_challenger_layer_4_context"] = layer_4_context
    analysis.run_parameters = run_parameters
    flag_modified(analysis, "run_parameters")
    session.commit()


def _create_devils_advocate_prepass_run(*, session: Session, analysis: Analysis, document: Document) -> PredictedCommentRun | None:
    skill = _resolve_predicted_comments_skill(session=session, document=document)
    if skill is None or skill.name != "devils_advocate_predefense":
        return None

    run_parameters = _predicted_comment_run_parameters(analysis=analysis, document=document, skill=skill)
    predicted_run = PredictedCommentRun(
        analysis_id=analysis.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=analysis.provider,
        model=analysis.model,
        status=RunStatus.QUEUED.value,
        run_parameters=run_parameters,
    )
    session.add(predicted_run)
    session.flush()
    _attach_predicted_comment_snapshots(
        session=session,
        predicted_run=predicted_run,
        skill=skill,
        document=document,
        analysis=analysis,
        run_parameters=run_parameters,
    )
    predicted_run.run_parameters = dict(run_parameters)
    flag_modified(predicted_run, "run_parameters")
    session.commit()
    return predicted_run


def _predicted_comment_run_parameters(*, analysis: Analysis, document: Document, skill: Skill) -> dict:
    run_parameters = {
        "main_analysis_id": str(analysis.id),
        "main_analysis_skill_source_snapshot": analysis.run_parameters.get("skill_source_snapshot"),
        "document_type": document.manual_document_type or document.detected_document_type,
        "output_language": analysis.run_parameters.get("output_language", "ru"),
        "snapshot_mode": analysis.run_parameters.get("snapshot_mode", "production_latest"),
        "max_output_tokens": _predicted_comments_max_output_tokens(analysis.run_parameters),
        "skill_source_snapshot": skill_source_snapshot(skill),
        "run_order": "before_gate_challenger",
    }
    mock_result = analysis.run_parameters.get("predicted_comments_mock_provider_result")
    if mock_result is not None:
        run_parameters["mock_provider_result"] = mock_result
    if skill.name == "devils_advocate_predefense":
        run_parameters["response_format"] = {"type": "json_object"}
    return run_parameters


def _build_gate_challenger_layer_4_context(predicted_run: PredictedCommentRun) -> dict | None:
    structured = predicted_run.structured_output or {}
    brutal_truth = structured.get("brutal_truth")
    detected_contradictions = structured.get("detected_contradictions") or []
    if not brutal_truth and not detected_contradictions:
        return None
    return {
        "source": "devils_advocate_predefense",
        "predicted_comment_run_id": str(predicted_run.id),
        "brutal_truth": brutal_truth or "",
        "detected_contradictions": detected_contradictions,
        "markdown": _format_layer_4_markdown(
            brutal_truth=brutal_truth or "",
            detected_contradictions=detected_contradictions,
        ),
    }


def _format_layer_4_markdown(*, brutal_truth: str, detected_contradictions: list) -> str:
    lines = [
        "Layer 4 - Devil's Advocate expert analysis",
        "These are results of expert analysis produced before Gate Challenger. Use them to strengthen or "
        "supplement Gate Challenger: add additional document-grounded findings when Devil's Advocate found "
        "something extra, or reinforce the position of problems Gate Challenger also finds. Do not treat "
        "unsupported expert claims as document evidence.",
        "",
        "1. The Brutal Truth",
        brutal_truth or "No brutal truth block was captured.",
        "",
        "2. Detected Contradictions & Missing Proofs",
    ]
    if detected_contradictions:
        lines.extend(_format_detected_contradictions(detected_contradictions))
    else:
        lines.append("No detected contradictions or missing proofs were captured.")
    return "\n".join(lines)


def _format_detected_contradictions(detected_contradictions: list) -> list[str]:
    lines = []
    for index, item in enumerate(detected_contradictions, start=1):
        if isinstance(item, dict):
            title = item.get("title") or item.get("section") or f"Item {index}"
            body = item.get("body") or item.get("issue") or item.get("comment") or ""
            severity = item.get("severity")
            citations = item.get("citations") or []
            line = f"{index}. {title}"
            if severity:
                line += f" [{severity}]"
            if body:
                line += f": {body}"
            if citations:
                line += f" Citations: {', '.join(str(citation) for citation in citations)}"
            lines.append(line)
        else:
            lines.append(f"{index}. {item}")
    return lines


def _validate_skill_source_available(*, skill: Skill, snapshot: dict | None) -> None:
    if not snapshot:
        return
    if snapshot.get("id") or snapshot.get("artifact_path"):
        return
    source_type = snapshot.get("source_type") or skill.source_type
    if source_type == SkillSourceType.INLINE_PROMPT.value:
        return
    expected_fingerprint = snapshot.get("source_fingerprint")
    if not expected_fingerprint:
        return
    try:
        material = refresh_skill_source_material(skill)
    except SkillSourceValidationError as exc:
        raise RuntimeError("skill_source_unavailable") from exc
    if material.source_fingerprint != expected_fingerprint:
        raise RuntimeError("skill_source_unavailable")


def _attach_predicted_comment_snapshots(
    *,
    session: Session,
    predicted_run: PredictedCommentRun,
    skill: Skill,
    document: Document,
    analysis: Analysis,
    run_parameters: dict,
) -> None:
    if not skill.skill_source_id or skill.runtime_mode != "snapshot_required":
        return
    source = session.get(SkillSource, skill.skill_source_id)
    if source is None:
        raise RuntimeError("skill_source_missing")
    storage = LocalDocumentStorage(get_settings().storage_root)
    snapshot_mode = run_parameters.get("snapshot_mode", "production_latest")
    source_snapshot = create_skill_source_snapshot(
        db=session,
        storage=storage,
        source=source,
        analysis_id=None,
        predicted_comment_run_id=predicted_run.id,
        snapshot_mode=snapshot_mode,
    )
    retrieval_snapshot = create_devils_retrieval_snapshot(
        db=session,
        storage=storage,
        source_snapshot=source_snapshot,
        predicted_run=predicted_run,
        document=document,
        analysis=analysis,
    )
    analysis_run_parameters = analysis.run_parameters or {}
    base_skill_snapshot = run_parameters.get("skill_source_snapshot") or {}
    run_parameters["main_analysis_source_snapshot_id"] = analysis_run_parameters.get("source_snapshot_id")
    run_parameters["skill_source_snapshot_id"] = str(source_snapshot.id)
    run_parameters["retrieval_snapshot_id"] = str(retrieval_snapshot.id)
    run_parameters["skill_source_snapshot"] = {
        **base_skill_snapshot,
        "id": str(source_snapshot.id),
        "source_slug": source_snapshot.source_slug,
        "source_revision": source_snapshot.resolved_revision,
        "source_fingerprint": source_snapshot.source_fingerprint,
        "artifact_path": source_snapshot.artifact_path,
        "snapshot_mode": source_snapshot.snapshot_mode,
        "is_dirty": source_snapshot.is_dirty,
    }
    run_parameters["retrieval_snapshot"] = {
        "id": str(retrieval_snapshot.id),
        "artifact_path": retrieval_snapshot.artifact_path,
        "retrieval_mode": retrieval_snapshot.retrieval_mode,
        "retrieval_version": retrieval_snapshot.retrieval_version,
        "corpus_fingerprint": retrieval_snapshot.corpus_fingerprint,
        "query_fingerprint": retrieval_snapshot.query_fingerprint,
        "selected_items": retrieval_snapshot.selected_items,
    }


def _resolve_predicted_comments_skill(*, session: Session, document: Document) -> Skill | None:
    document_type = document.manual_document_type or document.detected_document_type
    base_statement = select(Skill).where(
        Skill.status == EntityStatus.ACTIVE.value,
        Skill.skill_type == SkillType.PREDICTED_COMMENTS.value,
    )
    preferred = session.execute(
        base_statement.where(Skill.name == "devils_advocate_predefense").order_by(Skill.created_at.desc())
    ).scalars().first()
    if preferred and document_type in (preferred.supported_document_types or []):
        return preferred
    return session.execute(
        base_statement.where(Skill.name == "generic_predicted_comments_fallback").order_by(Skill.created_at.desc())
    ).scalars().first()


def _predicted_comments_max_output_tokens(run_parameters: dict) -> int:
    explicit = run_parameters.get("predicted_comments_max_output_tokens")
    if explicit is not None:
        return int(explicit)
    inherited = run_parameters.get("max_output_tokens")
    if inherited is not None:
        return int(inherited)
    return DEFAULT_PREDICTED_COMMENTS_MAX_OUTPUT_TOKENS

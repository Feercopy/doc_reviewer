import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.core.config import default_skill_source_snapshot_mode, get_settings
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
from app.services.analysis_jobs import enqueue_run_ic_agentic_review
from app.services.analyses import ANALYSIS_CHAIN_CANCEL_REQUESTED_AT_KEY
from app.services.devils_retrieval import create_devils_retrieval_snapshot
from app.services.ic_review import create_automatic_ic_review_run_for_analysis, mark_ic_review_run_enqueue_failed
from app.services.provider_keys import get_shared_provider_key
from app.services.skill_snapshots import create_skill_source_snapshot
from app.services.skill_sources import SkillSourceValidationError, refresh_skill_source_material
from app.services.skills import skill_source_snapshot
from app.storage.local import LocalDocumentStorage
from jobs.run_predicted_comments import run_predicted_comments
from providers.base import ProviderResponseRequest, ProviderRunRequest
from providers.registry import get_provider_adapter
from results.schema_validation import parse_and_validate_json_output
from skills.layer_4_synthesis import build_layer_4_synthesis, format_layer_4_synthesis_markdown
from skills.prompt_renderer import render_prompt


DEFAULT_PREDICTED_COMMENTS_MAX_OUTPUT_TOKENS = 20000
SUMMARY_SCHEMA_PATH = "contracts/schemas/main-analysis-summary-result.schema.json"


def run_analysis(
    analysis_id: str,
    *,
    db: Session | None = None,
    enqueue_predicted_comments=None,
    enqueue_ic_review=None,
) -> None:
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
        analysis = _claim_queued_analysis(session=session, analysis_uuid=analysis_uuid)
        if analysis is None:
            existing = session.get(Analysis, analysis_uuid)
            if existing is None:
                raise ValueError(f"Analysis {analysis_id} not found")
            if existing.status == RunStatus.CANCELLED.value:
                worker_logger.info(
                    "worker_job_cancelled",
                    extra={"job_type": "run_analysis", "entity_id": str(analysis_uuid), "status": "cancelled"},
                )
            return

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
        if _analysis_cancelled(session=session, analysis=analysis):
            worker_logger.info(
                "worker_job_cancelled",
                extra={"job_type": "run_analysis", "entity_id": str(analysis_uuid), "status": "cancelled"},
            )
            return

        use_summary_schema = _should_use_gate_challenger_summary_schema(skill=skill)
        use_responses_api = _should_use_responses_api(
            analysis=analysis,
            provider=provider,
            provider_key=provider_key,
            skill=skill,
        )
        schema_path = SUMMARY_SCHEMA_PATH if use_summary_schema else skill.result_schema_path
        if use_responses_api:
            run_parameters = dict(analysis.run_parameters or {})
            run_parameters["provider_api"] = "responses"
            analysis.run_parameters = run_parameters
            flag_modified(analysis, "run_parameters")
            session.commit()

        schema = json.loads(_resolve_schema_path(schema_path).read_text(encoding="utf-8"))
        prompt = _render_and_persist_prompt(session=session, analysis=analysis, document=document, skill=skill, schema=schema)
        if use_responses_api:
            request = ProviderResponseRequest(
                provider=provider,
                model=analysis.model,
                api_key=api_key,
                base_url=provider_key.base_url if provider_key else None,
                input=prompt,
                response_schema=schema,
                run_parameters=analysis.run_parameters,
            )
            result = get_provider_adapter(provider, analysis.run_parameters).run_response(request)
        else:
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
        if _analysis_cancelled(session=session, analysis=analysis):
            worker_logger.info(
                "worker_job_cancelled",
                extra={"job_type": "run_analysis", "entity_id": str(analysis_uuid), "status": "cancelled"},
            )
            return
        structured = parse_and_validate_json_output(
            structured_text=result.structured_text,
            schema_path=schema_path,
        )

        completed_run_parameters = analysis.run_parameters
        if use_responses_api:
            run_parameters = dict(completed_run_parameters or {})
            response_id = result.provider_metadata.get("response_id")
            if response_id:
                run_parameters["gate_challenger_response_id"] = response_id
            run_parameters["provider_api"] = "responses"
            completed_run_parameters = run_parameters
        if not _complete_analysis_if_running(
            session=session,
            analysis=analysis,
            structured=structured,
            raw_output=result.raw_output,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            estimated_cost=result.estimated_cost,
            run_parameters=completed_run_parameters,
        ):
            worker_logger.info(
                "worker_job_cancelled",
                extra={"job_type": "run_analysis", "entity_id": str(analysis_uuid), "status": "cancelled"},
            )
            return
        _create_and_enqueue_automatic_ic_review(
            session=session,
            analysis=analysis,
            enqueue_ic_review=enqueue_ic_review if enqueue_ic_review is not None else (
                enqueue_run_ic_agentic_review if owns_session else None
            ),
        )
        worker_logger.info(
            "worker_job_completed",
            extra={"job_type": "run_analysis", "entity_id": str(analysis_uuid), "status": "completed"},
        )
    except Exception as exc:
        session.rollback()
        if not _fail_analysis_if_active(
            session=session,
            analysis_uuid=analysis_uuid,
            exc=exc,
            provider_raw_output=provider_raw_output,
            provider_structured_text=provider_structured_text,
        ):
            existing = session.get(Analysis, analysis_uuid)
            if existing is None:
                raise
            worker_logger.info(
                "worker_job_cancelled",
                extra={"job_type": "run_analysis", "entity_id": str(analysis_uuid), "status": existing.status},
            )
            return
        failed = session.get(Analysis, analysis_uuid)
        if failed is None:
            raise
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
    return get_shared_provider_key(db=session, provider=provider)


def _claim_queued_analysis(*, session: Session, analysis_uuid: UUID) -> Analysis | None:
    started_at = utc_now()
    result = session.execute(
        update(Analysis)
        .where(Analysis.id == analysis_uuid, Analysis.status == RunStatus.QUEUED.value)
        .values(status=RunStatus.RUNNING.value, started_at=started_at, error_message=None)
    )
    if result.rowcount != 1:
        session.rollback()
        return None
    session.commit()
    return session.get(Analysis, analysis_uuid)


def _analysis_cancelled(*, session: Session, analysis: Analysis) -> bool:
    session.refresh(analysis)
    return analysis.status == RunStatus.CANCELLED.value


def _complete_analysis_if_running(
    *,
    session: Session,
    analysis: Analysis,
    structured: dict,
    raw_output: str,
    input_tokens: int | None,
    output_tokens: int | None,
    latency_ms: int | None,
    estimated_cost,
    run_parameters: dict,
) -> bool:
    completed_at = utc_now()
    result = session.execute(
        update(Analysis)
        .where(Analysis.id == analysis.id, Analysis.status == RunStatus.RUNNING.value)
        .values(
            structured_output=structured,
            raw_output=raw_output,
            verdict=structured.get("verdict"),
            summary=structured.get("summary"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            estimated_cost=estimated_cost,
            run_parameters=run_parameters,
            status=RunStatus.COMPLETED.value,
            completed_at=completed_at,
        )
    )
    if result.rowcount != 1:
        session.rollback()
        session.refresh(analysis)
        return False
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
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    )
    session.commit()
    session.refresh(analysis)
    return True


def _fail_analysis_if_active(
    *,
    session: Session,
    analysis_uuid: UUID,
    exc: Exception,
    provider_raw_output: str | None,
    provider_structured_text: str | None,
) -> bool:
    failed = session.get(Analysis, analysis_uuid)
    if failed is None:
        return False
    raw_output = failed.raw_output
    if provider_raw_output is not None and raw_output is None:
        raw_output = provider_raw_output or provider_structured_text
    completed_at = utc_now()
    result = session.execute(
        update(Analysis)
        .where(Analysis.id == analysis_uuid, Analysis.status.in_([RunStatus.QUEUED.value, RunStatus.RUNNING.value]))
        .values(
            status=RunStatus.FAILED.value,
            error_message=str(exc),
            raw_output=raw_output,
            completed_at=completed_at,
        )
    )
    if result.rowcount != 1:
        session.rollback()
        return False
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
    return True


def _create_and_enqueue_automatic_ic_review(*, session: Session, analysis: Analysis, enqueue_ic_review) -> None:
    try:
        session.refresh(analysis)
        if _analysis_chain_cancel_requested(analysis):
            worker_logger.info(
                "automatic_ic_review_skipped_cancelled_chain",
                extra={"job_type": "run_analysis", "entity_id": str(analysis.id), "status": analysis.status},
            )
            return
        output_language = str((analysis.run_parameters or {}).get("output_language") or "ru")
        check_run = create_automatic_ic_review_run_for_analysis(
            db=session,
            analysis=analysis,
            output_language=output_language,
        )
        if getattr(check_run, "created_for_request", False) and enqueue_ic_review is not None:
            try:
                enqueue_ic_review(check_run.id)
            except Exception as exc:
                mark_ic_review_run_enqueue_failed(db=session, run_id=check_run.id, error_message=str(exc))
                raise
        worker_logger.info(
            "automatic_ic_review_requested",
            extra={
                "job_type": "run_analysis",
                "entity_id": str(analysis.id),
                "analysis_check_run_id": str(check_run.id),
                "status": check_run.status,
            },
        )
    except Exception as exc:
        session.rollback()
        worker_logger.info(
            "automatic_ic_review_request_failed",
            extra={
                "job_type": "run_analysis",
                "entity_id": str(analysis.id),
                "status": "failed",
                "error_class": exc.__class__.__name__,
            },
        )


def _analysis_chain_cancel_requested(analysis: Analysis) -> bool:
    return bool((analysis.run_parameters or {}).get(ANALYSIS_CHAIN_CANCEL_REQUESTED_AT_KEY))


def _should_use_gate_challenger_summary_schema(*, skill: Skill) -> bool:
    return skill.name == "gate2_challenger_main_analysis"


def _should_use_responses_api(
    *,
    analysis: Analysis,
    provider: Provider,
    provider_key: ProviderKey | None,
    skill: Skill,
) -> bool:
    if skill.name != "gate2_challenger_main_analysis":
        return False
    if provider != Provider.OPENAI_COMPATIBLE:
        return False
    parameters = analysis.run_parameters or {}
    if parameters.get("provider_api") == "chat_completions":
        return False
    if parameters.get("provider_api") == "responses":
        return True
    if "mock_provider_response_result" in parameters:
        return True
    if not _openai_compatible_base_url_supports_responses(provider_key.base_url if provider_key else None):
        return False
    return "mock_provider_result" not in parameters


def _openai_compatible_base_url_supports_responses(base_url: str | None) -> bool:
    if not base_url:
        return True
    hostname = (urlparse(base_url).hostname or "").lower()
    return hostname in {"api.openai.com"}


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
        "devils_advocate_output_contract": "compact_prepass",
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
    synthesis = build_layer_4_synthesis(structured)
    if not brutal_truth and not detected_contradictions and not synthesis.get("must_review_signals"):
        return None
    return {
        "source": "devils_advocate_predefense",
        "predicted_comment_run_id": str(predicted_run.id),
        "brutal_truth": brutal_truth or "",
        "detected_contradictions": detected_contradictions,
        "synthesis": synthesis,
        "markdown": _format_layer_4_markdown(
            brutal_truth=brutal_truth or "",
            detected_contradictions=detected_contradictions,
            synthesis=synthesis,
        ),
    }


def _format_layer_4_markdown(*, brutal_truth: str, detected_contradictions: list, synthesis: dict | None = None) -> str:
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
    synthesis_markdown = format_layer_4_synthesis_markdown(synthesis)
    if synthesis_markdown:
        lines.extend(["", "3. Structured synthesis contract", synthesis_markdown])
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
    snapshot_mode = run_parameters.get("snapshot_mode") or default_skill_source_snapshot_mode()
    source_snapshot = create_skill_source_snapshot(
        db=session,
        storage=storage,
        source=source,
        analysis_id=None,
        predicted_comment_run_id=predicted_run.id,
        analysis_check_run_id=None,
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

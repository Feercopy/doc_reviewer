import hashlib
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.logging import worker_logger
from app.models.analysis import Analysis, AnalysisDetailRun
from app.models.provider_key import ProviderKey
from app.models.base import utc_now
from app.schemas.enums import Provider, RunStatus
from app.security.secrets import decrypt_secret
from app.services.provider_keys import get_shared_provider_key
from app.storage.local import LocalDocumentStorage
from providers.base import ProviderResponseRequest
from providers.registry import get_provider_adapter
from results.schema_validation import parse_and_validate_json_output
from skills.output_language import output_language_instruction


DETAILS_SCHEMA_PATH = "contracts/schemas/main-analysis-details-result.schema.json"


def run_analysis_details(detail_run_id: str, *, db: Session | None = None) -> None:
    owns_session = db is None
    session = db or SessionLocal()
    detail_uuid = UUID(str(detail_run_id))
    provider_raw_output = None
    provider_structured_text = None
    try:
        worker_logger.info(
            "worker_job_started",
            extra={"job_type": "run_analysis_details", "entity_id": str(detail_uuid), "status": "running"},
        )
        detail_run = _claim_queued_detail_run(session=session, detail_uuid=detail_uuid)
        if detail_run is None:
            existing = session.get(AnalysisDetailRun, detail_uuid)
            if existing is None:
                raise ValueError(f"Analysis detail run {detail_run_id} not found")
            if existing.status == RunStatus.CANCELLED.value:
                worker_logger.info(
                    "worker_job_cancelled",
                    extra={"job_type": "run_analysis_details", "entity_id": str(detail_uuid), "status": "cancelled"},
                )
            return
        analysis = session.get(Analysis, detail_run.analysis_id)
        if analysis is None:
            raise RuntimeError("analysis_context_missing")

        _set_summary_details_status(analysis=analysis, status=RunStatus.RUNNING.value, detail_run=detail_run)
        session.commit()

        provider = Provider(detail_run.provider)
        provider_key = _get_provider_key(session, provider)
        if provider != Provider.HERMES and provider_key is None:
            raise RuntimeError("provider_key_missing")
        api_key = decrypt_secret(provider_key.encrypted_api_key) if provider_key else None

        previous_response_id = detail_run.previous_response_id or (analysis.run_parameters or {}).get(
            "gate_challenger_response_id"
        )
        if not previous_response_id:
            raise RuntimeError("previous_response_id_missing")

        schema = json.loads(_resolve_schema_path(DETAILS_SCHEMA_PATH).read_text(encoding="utf-8"))
        prompt = _render_and_persist_detail_prompt(
            session=session,
            analysis=analysis,
            detail_run=detail_run,
            schema=schema,
            previous_response_id=str(previous_response_id),
        )
        request = ProviderResponseRequest(
            provider=provider,
            model=detail_run.model,
            api_key=api_key,
            base_url=provider_key.base_url if provider_key else None,
            input=prompt,
            response_schema=schema,
            previous_response_id=str(previous_response_id),
            run_parameters={**(analysis.run_parameters or {}), **(detail_run.run_parameters or {})},
        )
        result = get_provider_adapter(provider, detail_run.run_parameters).run_response(request)
        provider_raw_output = result.raw_output
        provider_structured_text = result.structured_text
        if _detail_run_cancelled(session=session, detail_run=detail_run):
            worker_logger.info(
                "worker_job_cancelled",
                extra={"job_type": "run_analysis_details", "entity_id": str(detail_uuid), "status": "cancelled"},
            )
            return
        structured = parse_and_validate_json_output(
            structured_text=result.structured_text,
            schema_path=DETAILS_SCHEMA_PATH,
        )

        if not _complete_detail_run_if_running(
            session=session,
            detail_run=detail_run,
            analysis=analysis,
            previous_response_id=str(previous_response_id),
            response_id=result.provider_metadata.get("response_id"),
            structured=structured,
            raw_output=result.raw_output,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            estimated_cost=result.estimated_cost,
        ):
            worker_logger.info(
                "worker_job_cancelled",
                extra={"job_type": "run_analysis_details", "entity_id": str(detail_uuid), "status": "cancelled"},
            )
            return
        worker_logger.info(
            "worker_job_completed",
            extra={"job_type": "run_analysis_details", "entity_id": str(detail_uuid), "status": "completed"},
        )
    except Exception as exc:
        session.rollback()
        if not _fail_detail_run_if_active(
            session=session,
            detail_uuid=detail_uuid,
            exc=exc,
            provider_raw_output=provider_raw_output,
            provider_structured_text=provider_structured_text,
        ):
            existing = session.get(AnalysisDetailRun, detail_uuid)
            if existing is None:
                raise
            worker_logger.info(
                "worker_job_cancelled",
                extra={"job_type": "run_analysis_details", "entity_id": str(detail_uuid), "status": existing.status},
            )
            return
        failed = session.get(AnalysisDetailRun, detail_uuid)
        if failed is None:
            raise
        worker_logger.info(
            "worker_job_failed",
            extra={
                "job_type": "run_analysis_details",
                "entity_id": str(detail_uuid),
                "status": "failed",
                "error_class": exc.__class__.__name__,
            },
        )
    finally:
        if owns_session:
            session.close()


def _get_provider_key(session: Session, provider: Provider) -> ProviderKey | None:
    return get_shared_provider_key(db=session, provider=provider)


def _claim_queued_detail_run(*, session: Session, detail_uuid: UUID) -> AnalysisDetailRun | None:
    result = session.execute(
        update(AnalysisDetailRun)
        .where(AnalysisDetailRun.id == detail_uuid, AnalysisDetailRun.status == RunStatus.QUEUED.value)
        .values(status=RunStatus.RUNNING.value, started_at=utc_now(), error_message=None)
    )
    if result.rowcount != 1:
        session.rollback()
        return None
    session.commit()
    return session.get(AnalysisDetailRun, detail_uuid)


def _detail_run_cancelled(*, session: Session, detail_run: AnalysisDetailRun) -> bool:
    session.refresh(detail_run)
    return detail_run.status == RunStatus.CANCELLED.value


def _complete_detail_run_if_running(
    *,
    session: Session,
    detail_run: AnalysisDetailRun,
    analysis: Analysis,
    previous_response_id: str,
    response_id: str | None,
    structured: dict,
    raw_output: str,
    input_tokens: int | None,
    output_tokens: int | None,
    latency_ms: int | None,
    estimated_cost,
) -> bool:
    result = session.execute(
        update(AnalysisDetailRun)
        .where(AnalysisDetailRun.id == detail_run.id, AnalysisDetailRun.status == RunStatus.RUNNING.value)
        .values(
            previous_response_id=previous_response_id,
            response_id=response_id,
            structured_output=structured,
            raw_output=raw_output,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            estimated_cost=estimated_cost,
            status=RunStatus.COMPLETED.value,
            completed_at=utc_now(),
        )
    )
    if result.rowcount != 1:
        session.rollback()
        session.refresh(detail_run)
        return False
    _set_summary_details_status(analysis=analysis, status=RunStatus.COMPLETED.value, detail_run=detail_run)
    session.commit()
    session.refresh(detail_run)
    return True


def _fail_detail_run_if_active(
    *,
    session: Session,
    detail_uuid: UUID,
    exc: Exception,
    provider_raw_output: str | None,
    provider_structured_text: str | None,
) -> bool:
    failed = session.get(AnalysisDetailRun, detail_uuid)
    if failed is None:
        return False
    raw_output = failed.raw_output
    if provider_raw_output is not None and raw_output is None:
        raw_output = provider_raw_output or provider_structured_text
    result = session.execute(
        update(AnalysisDetailRun)
        .where(AnalysisDetailRun.id == detail_uuid, AnalysisDetailRun.status.in_([RunStatus.QUEUED.value, RunStatus.RUNNING.value]))
        .values(
            status=RunStatus.FAILED.value,
            error_message=str(exc),
            raw_output=raw_output,
            completed_at=utc_now(),
        )
    )
    if result.rowcount != 1:
        session.rollback()
        return False
    analysis = session.get(Analysis, failed.analysis_id)
    if analysis is not None:
        _set_summary_details_status(analysis=analysis, status=RunStatus.FAILED.value, detail_run=failed)
    session.commit()
    return True


def _resolve_schema_path(schema_path: str) -> Path:
    return Path(__file__).resolve().parents[3] / schema_path


def _render_and_persist_detail_prompt(
    *,
    session: Session,
    analysis: Analysis,
    detail_run: AnalysisDetailRun,
    schema: dict,
    previous_response_id: str,
) -> str:
    language = (detail_run.run_parameters or {}).get("output_language") or (analysis.run_parameters or {}).get(
        "output_language"
    )
    parts = [
        "Gate Challenger lazy detail expansion.",
        "Use the existing Responses API conversation state addressed by previous_response_id.",
        f"previous_response_id: {previous_response_id}",
        output_language_instruction(language) if language is not None else "",
        "Expand the already produced Gate Challenger analysis state into full Layer 1 and Layer 2 details.",
        "Preserve the original verdict and summary unless the details contradict the summary result.",
        "Do not invent new document evidence. Use only evidence already considered in the previous Gate Challenger analysis.",
        "If details contradict the Stage 2 verdict, keep the original verdict field stable, set revision_required to true, "
        "and explain the contradiction in revision_reason.",
        "Compact Stage 2 structured output:",
        json.dumps(analysis.structured_output or {}, ensure_ascii=False, sort_keys=True),
        "Return only JSON matching this schema:",
        json.dumps(schema, ensure_ascii=False, sort_keys=True),
    ]
    prompt = "\n\n".join(part for part in parts if part)
    storage = LocalDocumentStorage(get_settings().storage_root)
    prompt_path = storage.save_rendered_prompt(analysis_id=detail_run.id, prompt=prompt)
    run_parameters = dict(detail_run.run_parameters or {})
    run_parameters["provider_api"] = "responses"
    run_parameters["previous_response_id"] = previous_response_id
    run_parameters["rendered_prompt_artifact_path"] = str(prompt_path)
    run_parameters["prompt_fingerprint"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    detail_run.run_parameters = run_parameters
    flag_modified(detail_run, "run_parameters")
    session.commit()
    return prompt


def _set_summary_details_status(*, analysis: Analysis, status: str, detail_run: AnalysisDetailRun) -> None:
    output = dict(analysis.structured_output or {})
    if not output:
        return
    output["details_status"] = status
    output["details_run_id"] = str(detail_run.id)
    analysis.structured_output = output
    flag_modified(analysis, "structured_output")

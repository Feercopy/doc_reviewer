import hashlib
import json
from pathlib import Path
from uuid import UUID

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
        detail_run = session.get(AnalysisDetailRun, detail_uuid)
        if detail_run is None:
            raise ValueError(f"Analysis detail run {detail_run_id} not found")
        if detail_run.status == RunStatus.CANCELLED.value:
            worker_logger.info(
                "worker_job_cancelled",
                extra={"job_type": "run_analysis_details", "entity_id": str(detail_uuid), "status": "cancelled"},
            )
            return
        analysis = session.get(Analysis, detail_run.analysis_id)
        if analysis is None:
            raise RuntimeError("analysis_context_missing")

        detail_run.status = RunStatus.RUNNING.value
        detail_run.started_at = utc_now()
        detail_run.error_message = None
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

        detail_run.previous_response_id = str(previous_response_id)
        detail_run.response_id = result.provider_metadata.get("response_id")
        detail_run.structured_output = structured
        detail_run.raw_output = result.raw_output
        detail_run.input_tokens = result.input_tokens
        detail_run.output_tokens = result.output_tokens
        detail_run.latency_ms = result.latency_ms
        detail_run.estimated_cost = result.estimated_cost
        detail_run.status = RunStatus.COMPLETED.value
        detail_run.completed_at = utc_now()
        _set_summary_details_status(analysis=analysis, status=RunStatus.COMPLETED.value, detail_run=detail_run)
        session.commit()
        worker_logger.info(
            "worker_job_completed",
            extra={"job_type": "run_analysis_details", "entity_id": str(detail_uuid), "status": "completed"},
        )
    except Exception as exc:
        session.rollback()
        failed = session.get(AnalysisDetailRun, detail_uuid)
        if failed is None:
            raise
        failed.status = RunStatus.FAILED.value
        failed.error_message = str(exc)
        if provider_raw_output is not None and failed.raw_output is None:
            failed.raw_output = provider_raw_output or provider_structured_text
        failed.completed_at = utc_now()
        analysis = session.get(Analysis, failed.analysis_id)
        if analysis is not None:
            _set_summary_details_status(analysis=analysis, status=RunStatus.FAILED.value, detail_run=failed)
        session.commit()
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


def _detail_run_cancelled(*, session: Session, detail_run: AnalysisDetailRun) -> bool:
    session.refresh(detail_run)
    return detail_run.status == RunStatus.CANCELLED.value


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

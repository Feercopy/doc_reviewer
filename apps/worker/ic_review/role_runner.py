from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import validate
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.analysis import Analysis, AnalysisCheckRun, AnalysisCheckStep
from app.models.base import utc_now
from app.schemas.enums import Provider, RunStatus
from app.storage.local import LocalDocumentStorage
from ic_review.context import ICReviewContext
from ic_review.context_pack import ICReviewContextPack
from ic_review.renderer import ROLE_SCHEMA_PATH, SnapshotTextReader, render_role_prompt
from ic_review.schema_normalization import normalize_schema_bounded_strings
from providers.base import AnalysisProviderResult, ProviderRunRequest
from providers.registry import get_provider_adapter
from results.schema_validation import parse_json_output

from .errors import IcReviewRunCancelled, safe_ic_review_error_message


IC_REVIEW_PROVIDER_TIMEOUT_SECONDS = 600
IC_REVIEW_PROVIDER_CONNECT_TIMEOUT_SECONDS = 30
IC_REVIEW_PROVIDER_MAX_RETRIES = 3
IC_REVIEW_ROLE_MAX_OUTPUT_TOKENS = 32000


def run_role_step(
    *,
    session: Session,
    check_run: AnalysisCheckRun,
    analysis: Analysis,
    role: str,
    context: ICReviewContext,
    context_pack: ICReviewContextPack | None = None,
    source_snapshot: SnapshotTextReader,
    api_key: str | None = None,
    base_url: str | None = None,
    storage: LocalDocumentStorage | None = None,
    run_parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = Provider(check_run.provider)
    effective_run_parameters = _role_run_parameters(
        base_parameters=check_run.run_parameters or {},
        role=role,
        overrides=run_parameters,
    )
    schema = _load_schema(ROLE_SCHEMA_PATH)

    step = AnalysisCheckStep(
        check_run_id=check_run.id,
        step_type="role",
        step_name=role,
        status=RunStatus.RUNNING.value,
        started_at=utc_now(),
    )
    session.add(step)
    session.commit()

    provider_raw_output: str | None = None
    provider_structured_text: str | None = None
    try:
        prompt = render_role_prompt(
            role=role,
            context=context,
            context_pack=context_pack,
            source_snapshot=source_snapshot,
            role_schema=schema,
        )
        storage_backend = storage or LocalDocumentStorage(get_settings().storage_root)
        prompt_path = write_prompt_artifact(
            storage=storage_backend,
            analysis_id=analysis.id,
            run_id=check_run.id,
            step_name=role,
            prompt=prompt,
        )
        step.prompt_artifact_path = str(prompt_path)
        step.prompt_fingerprint = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        session.commit()

        result, json_retry = _run_role_provider_with_json_retry(
            provider=provider,
            model=check_run.model,
            api_key=api_key,
            base_url=base_url,
            prompt=prompt,
            response_schema=schema,
            run_parameters=effective_run_parameters,
            role=role,
        )
        provider_raw_output = result.raw_output
        provider_structured_text = result.structured_text
        step.raw_output = result.raw_output or result.structured_text
        step.input_tokens = result.input_tokens
        step.output_tokens = result.output_tokens
        step.latency_ms = result.latency_ms
        step.estimated_cost = result.estimated_cost
        if json_retry is not None:
            step.artifacts = [*list(step.artifacts or []), json_retry]
        session.commit()
        if _check_run_cancelled(session=session, check_run=check_run, step=step):
            raise IcReviewRunCancelled("ic_review_cancelled")

        payload = parse_json_output(result.structured_text)
        structured = normalize_schema_bounded_strings(payload, schema, schema)
        validate(instance=structured, schema=schema)
        step.structured_output = structured
        step.status = RunStatus.COMPLETED.value
        step.completed_at = utc_now()
        session.commit()
        return structured
    except IcReviewRunCancelled:
        raise
    except Exception as exc:
        session.rollback()
        safe_error = safe_ic_review_error_message(exc)
        failed_step = session.get(AnalysisCheckStep, step.id)
        if failed_step is None:
            raise
        failed_step.status = RunStatus.FAILED.value
        failed_step.error_message = safe_error
        raw_to_preserve = provider_raw_output or provider_structured_text
        if raw_to_preserve is not None and not failed_step.raw_output:
            failed_step.raw_output = provider_raw_output or provider_structured_text
        failed_step.completed_at = utc_now()
        failed_run = session.get(AnalysisCheckRun, check_run.id)
        if failed_run is not None:
            failed_run.status = RunStatus.FAILED.value
            failed_run.current_stage = f"failed:{role}"
            failed_run.error_message = safe_error
            failed_run.completed_at = utc_now()
        session.commit()
        raise


def write_prompt_artifact(
    *,
    storage: LocalDocumentStorage,
    analysis_id: Any,
    run_id: Any,
    step_name: str,
    prompt: str,
) -> Path:
    run_dir = storage.ic_review_run_dir(analysis_id=analysis_id, run_id=run_id)
    prompt_dir = _owned_child(run_dir, "prompts")
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = _owned_child(prompt_dir, f"{_safe_step_name(step_name)}.txt")
    prompt_path.write_text(prompt, encoding="utf-8")
    return prompt_path


def _role_run_parameters(
    *,
    base_parameters: dict[str, Any],
    role: str,
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    parameters = dict(base_parameters)
    if overrides:
        parameters.update(overrides)
    role_mock_results = parameters.get("role_mock_provider_results")
    if (
        isinstance(role_mock_results, dict)
        and role in role_mock_results
    ):
        parameters["mock_provider_result"] = role_mock_results[role]
    apply_ic_review_provider_defaults(parameters)
    parameters.setdefault("max_output_tokens", IC_REVIEW_ROLE_MAX_OUTPUT_TOKENS)
    parameters["ic_review_role"] = role
    return parameters


def _run_role_provider_with_json_retry(
    *,
    provider: Provider,
    model: str,
    api_key: str | None,
    base_url: str | None,
    prompt: str,
    response_schema: dict,
    run_parameters: dict[str, Any],
    role: str,
) -> tuple[AnalysisProviderResult, dict[str, Any] | None]:
    result = _call_role_provider(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        prompt=prompt,
        response_schema=response_schema,
        run_parameters=run_parameters,
    )
    try:
        parse_json_output(result.structured_text)
    except json.JSONDecodeError as exc:
        retry_parameters = _role_json_retry_run_parameters(run_parameters=run_parameters, role=role)
        retry_result = _call_role_provider(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            prompt=_role_json_retry_prompt(prompt=prompt, error=exc),
            response_schema=response_schema,
            run_parameters=retry_parameters,
        )
        return retry_result, {
            "key": "role_json_retry",
            "kind": "metadata",
            "attempts": 2,
            "reason": exc.msg,
            "retry_step": retry_parameters["ic_review_step"],
        }
    return result, None


def _call_role_provider(
    *,
    provider: Provider,
    model: str,
    api_key: str | None,
    base_url: str | None,
    prompt: str,
    response_schema: dict,
    run_parameters: dict[str, Any],
) -> AnalysisProviderResult:
    return get_provider_adapter(provider, run_parameters).run(
        ProviderRunRequest(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            prompt=prompt,
            response_schema=response_schema,
            run_parameters=run_parameters,
        )
    )


def _role_json_retry_run_parameters(*, run_parameters: dict[str, Any], role: str) -> dict[str, Any]:
    parameters = dict(run_parameters)
    retry_mock_results = parameters.get("role_json_retry_mock_provider_results")
    if isinstance(retry_mock_results, dict) and role in retry_mock_results:
        parameters["mock_provider_result"] = retry_mock_results[role]
    parameters["ic_review_step"] = f"{role}:json_retry"
    parameters["max_output_tokens"] = max(int(parameters.get("max_output_tokens") or 0), IC_REVIEW_ROLE_MAX_OUTPUT_TOKENS)
    return parameters


def _role_json_retry_prompt(*, prompt: str, error: json.JSONDecodeError) -> str:
    return (
        prompt.rstrip()
        + "\n\n## JSON Retry Instruction\n"
        + f"The previous role response was not valid JSON: {error.msg}.\n"
        + "Regenerate the required role result as exactly one valid JSON object matching "
        + "`ic-agentic-role-result.schema.json`. Prioritize a complete, closed JSON object over breadth: "
        + "keep arrays within the schema limits, keep full_report_materials detailed but bounded, and do not "
        + "include Markdown fences, commentary, or prose outside the JSON object."
    )


def apply_ic_review_provider_defaults(parameters: dict[str, Any]) -> dict[str, Any]:
    parameters.setdefault("timeout_seconds", IC_REVIEW_PROVIDER_TIMEOUT_SECONDS)
    parameters.setdefault("connect_timeout_seconds", IC_REVIEW_PROVIDER_CONNECT_TIMEOUT_SECONDS)
    parameters.setdefault("max_retries", IC_REVIEW_PROVIDER_MAX_RETRIES)
    return parameters


def _check_run_cancelled(*, session: Session, check_run: AnalysisCheckRun, step: AnalysisCheckStep) -> bool:
    session.refresh(check_run)
    if check_run.status != RunStatus.CANCELLED.value:
        return False
    session.refresh(step)
    step.status = RunStatus.CANCELLED.value
    step.error_message = "cancelled_by_user"
    step.completed_at = utc_now()
    session.commit()
    return True


def _load_schema(schema_path: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    return json.loads((root / schema_path).read_text(encoding="utf-8"))


def _owned_child(parent: Path, child: str) -> Path:
    parent_root = parent.expanduser().resolve()
    path = (parent_root / child).resolve()
    if not path.is_relative_to(parent_root):
        raise ValueError("IC review artifact path escapes run directory")
    return path


def _safe_step_name(step_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", step_name).strip("._")
    return cleaned[:120] or "step"

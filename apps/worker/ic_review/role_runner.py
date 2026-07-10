from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.analysis import Analysis, AnalysisCheckRun, AnalysisCheckStep
from app.models.base import utc_now
from app.schemas.enums import Provider, RunStatus
from app.storage.local import LocalDocumentStorage
from ic_review.context import ICReviewContext
from ic_review.renderer import ROLE_SCHEMA_PATH, SnapshotTextReader, render_role_prompt
from providers.base import ProviderRunRequest
from providers.registry import get_provider_adapter
from results.schema_validation import parse_and_validate_json_output

from .errors import safe_ic_review_error_message


IC_REVIEW_PROVIDER_TIMEOUT_SECONDS = 600
IC_REVIEW_PROVIDER_CONNECT_TIMEOUT_SECONDS = 30
IC_REVIEW_PROVIDER_MAX_RETRIES = 3


def run_role_step(
    *,
    session: Session,
    check_run: AnalysisCheckRun,
    analysis: Analysis,
    role: str,
    context: ICReviewContext,
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

        request = ProviderRunRequest(
            provider=provider,
            model=check_run.model,
            api_key=api_key,
            base_url=base_url,
            prompt=prompt,
            response_schema=schema,
            run_parameters=effective_run_parameters,
        )
        result = get_provider_adapter(provider, effective_run_parameters).run(request)
        provider_raw_output = result.raw_output
        provider_structured_text = result.structured_text
        step.raw_output = result.raw_output or result.structured_text
        step.input_tokens = result.input_tokens
        step.output_tokens = result.output_tokens
        step.latency_ms = result.latency_ms
        step.estimated_cost = result.estimated_cost
        session.commit()

        structured = parse_and_validate_json_output(
            structured_text=result.structured_text,
            schema_path=ROLE_SCHEMA_PATH,
        )
        step.structured_output = structured
        step.status = RunStatus.COMPLETED.value
        step.completed_at = utc_now()
        session.commit()
        return structured
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
    parameters["ic_review_role"] = role
    return parameters


def apply_ic_review_provider_defaults(parameters: dict[str, Any]) -> dict[str, Any]:
    parameters.setdefault("timeout_seconds", IC_REVIEW_PROVIDER_TIMEOUT_SECONDS)
    parameters.setdefault("connect_timeout_seconds", IC_REVIEW_PROVIDER_CONNECT_TIMEOUT_SECONDS)
    parameters.setdefault("max_retries", IC_REVIEW_PROVIDER_MAX_RETRIES)
    return parameters


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

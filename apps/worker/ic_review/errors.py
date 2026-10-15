from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import traceback
from typing import Any
from uuid import UUID

from jsonschema import ValidationError
from rq import get_current_job
from sqlalchemy.exc import DBAPIError

from app.logging import worker_logger
from app.models.analysis import AnalysisCheckRun


class IcReviewRunCancelled(RuntimeError):
    pass


ERROR_DIAGNOSTICS_RUN_PARAMETER_KEY = "ic_review_error_diagnostics"

SAFE_ERROR_CODES = {
    "duplicate_prepared_statement",
    "formula_auditor_failed",
    "ic_review_artifact_path_escapes_run_dir",
    "ic_review_context_missing",
    "ic_review_document_missing",
    "ic_review_validation_failed",
    "invalid_synthesis_wrapper",
    "parent_analysis_not_completed",
    "provider_key_missing",
    "source_snapshot_artifact_path_escapes_storage_root",
    "source_snapshot_fingerprint_mismatch",
    "source_snapshot_id_mismatch",
    "source_snapshot_required",
    "workbook_parse_failed",
    "workbook_storage_path_escapes_run_upload_dir",
    "workbook_storage_path_missing",
    "workbook_storage_path_not_xlsx",
}
SAFE_ERROR_PREFIXES = (
    "invalid_legacy_report_json:",
    "invalid_synthesis_wrapper:",
    "missing_role_outputs:",
    "source_snapshot_missing:",
    "unsupported_ic_role:",
)


def safe_ic_review_error_message(exc: BaseException) -> str:
    """Return a user-visible error code without rejected provider content."""
    if isinstance(exc, json.JSONDecodeError):
        return f"invalid_json:{exc.msg}"
    if isinstance(exc, ValidationError):
        return _validation_error_message(exc)

    message = str(exc).strip()
    if _is_known_safe_error_code(message):
        return message

    cause = exc.__cause__
    if isinstance(cause, ValidationError):
        return _validation_error_message(cause)
    if isinstance(cause, json.JSONDecodeError):
        return f"invalid_json:{cause.msg}"
    if isinstance(exc, DBAPIError) and exc.orig is not None:
        dbapi_code = _exception_code(exc.orig)
        if dbapi_code in SAFE_ERROR_CODES:
            return dbapi_code

    return _exception_code(exc)


def _is_known_safe_error_code(message: str) -> bool:
    return message in SAFE_ERROR_CODES or any(message.startswith(prefix) for prefix in SAFE_ERROR_PREFIXES)


def _validation_error_message(exc: ValidationError) -> str:
    validator = str(exc.validator or "schema")
    validator = re.sub(r"[^A-Za-z0-9_.:-]+", "_", validator).strip("_") or "schema"
    return f"schema_validation_failed:{validator}"


def _exception_code(exc: BaseException) -> str:
    name = exc.__class__.__name__
    code = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return code or "ic_review_error"


def build_ic_review_error_diagnostics(
    exc: BaseException,
    *,
    phase: str,
    stage: str | None,
    step_name: str | None = None,
    provider_raw_output_present: bool | None = None,
    prompt_artifact_present: bool | None = None,
    context: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
    schema_name: str | None = None,
    elapsed_ms: int | None = None,
    provider_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    message = str(exc)
    diagnostic: dict[str, Any] = {
        "version": 2,
        "recorded_at": datetime.now(UTC).isoformat(),
        "code": safe_ic_review_error_message(exc),
        "phase": phase,
        "stage": stage,
        "step_name": step_name,
        "error_class": exc.__class__.__name__,
        "error_module": exc.__class__.__module__,
        "message_length": len(message),
        "message_sha256": hashlib.sha256(message.encode("utf-8", errors="replace")).hexdigest(),
        "traceback": _safe_traceback(exc),
        "context": _safe_context({"app_release_sha": _release_sha(), **(context or {})}),
    }
    if elapsed_ms is not None:
        diagnostic["elapsed_ms"] = max(0, elapsed_ms)
    if provider_attempts:
        diagnostic["provider_attempts"] = provider_attempts[:4]
    if schema is not None:
        diagnostic["schema"] = {
            "name": _identifier(schema_name),
            "sha256": hashlib.sha256(
                json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
    if exc.__cause__ is not None:
        diagnostic["cause_class"] = exc.__cause__.__class__.__name__
        diagnostic["cause_code"] = safe_ic_review_error_message(exc.__cause__)
    if exc.__context__ is not None and exc.__context__ is not exc.__cause__:
        diagnostic["context_class"] = exc.__context__.__class__.__name__
        diagnostic["context_code"] = safe_ic_review_error_message(exc.__context__)
    if provider_raw_output_present is not None:
        diagnostic["provider_raw_output_present"] = provider_raw_output_present
    if prompt_artifact_present is not None:
        diagnostic["prompt_artifact_present"] = prompt_artifact_present
    for error in _exception_chain(exc):
        db_error = _safe_db_error_details(error)
        if db_error and "db_error" not in diagnostic:
            diagnostic["db_error"] = db_error
        if isinstance(error, ValidationError) and "validation" not in diagnostic:
            diagnostic["validation"] = _validation_details(error, schema or {})
        if isinstance(error, json.JSONDecodeError) and "json_error" not in diagnostic:
            diagnostic["json_error"] = {"line": error.lineno, "column": error.colno, "position": error.pos}
        response = getattr(error, "response", None)
        status = getattr(error, "status_code", None) or getattr(response, "status_code", None)
        if type(status) is int and 100 <= status <= 599 and "provider_error" not in diagnostic:
            diagnostic["provider_error"] = {
                "status_code": status,
                "request_id": _provider_request_id(error),
            }
    return diagnostic


def build_ic_review_provider_attempt(
    *,
    attempt: int,
    elapsed_ms: int,
    error: BaseException | None = None,
    provider_metadata: dict[str, Any] | None = None,
    retry_delay_ms: int | None = None,
) -> dict[str, Any]:
    """Record transport metadata only; exception messages and response bodies are untrusted."""
    details: dict[str, Any] = {
        "attempt": attempt,
        "outcome": "error" if error is not None else "completed",
        "elapsed_ms": max(0, elapsed_ms),
        "http_status": None,
        "request_id": None,
        "response_id": None,
    }
    if error is not None:
        details["error_class"] = error.__class__.__name__
        details["transport_error_class"] = next(
            (cause.__class__.__name__ for cause in _exception_chain(error)[1:]
             if cause.__class__.__module__.startswith(("httpx", "httpcore"))),
            None,
        )
        for cause in _exception_chain(error):
            response = getattr(cause, "response", None)
            status = getattr(cause, "status_code", None) or getattr(response, "status_code", None)
            if details["http_status"] is None and type(status) is int and 100 <= status <= 599:
                details["http_status"] = status
            if details["request_id"] is None:
                details["request_id"] = _provider_request_id(cause)
    else:
        metadata = provider_metadata or {}
        status = metadata.get("response_status")
        if type(status) is int and 100 <= status <= 599:
            details["http_status"] = status
        details["request_id"] = _identifier(metadata.get("request_id"))
        details["response_id"] = _identifier(metadata.get("response_id"))
    if retry_delay_ms is not None:
        details["retry_delay_ms"] = max(0, retry_delay_ms)
    return details


def log_ic_review_provider_attempt(
    *,
    context: dict[str, Any],
    role: str,
    attempt: dict[str, Any],
    prompt_sha256: str,
    prompt_chars: int,
    timeout_seconds: float | None,
    connect_timeout_seconds: float | None,
) -> None:
    try:
        payload = {
            "context": _safe_context(context),
            "role": _identifier(role),
            "prompt_sha256": prompt_sha256,
            "prompt_chars": prompt_chars,
            "timeout_seconds": _safe_duration(timeout_seconds),
            "connect_timeout_seconds": _safe_duration(connect_timeout_seconds),
            **attempt,
        }
        log = worker_logger.warning if attempt.get("outcome") == "error" else worker_logger.info
        log("ic_review_provider_attempt %s", json.dumps(payload, ensure_ascii=True, sort_keys=True))
    except Exception:
        pass


def _provider_request_id(error: BaseException) -> str | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    return _identifier(getattr(error, "request_id", None)) or _identifier(
        headers.get("x-request-id") if headers is not None else None
    )


def _safe_duration(value: Any) -> float | None:
    if type(value) not in (int, float) or not 0 < value <= 3600 or not math.isfinite(value):
        return None
    return float(value)


def ic_review_diagnostic_context(
    check_run: AnalysisCheckRun,
    *,
    document_id: UUID | None = None,
    step_id: UUID | None = None,
) -> dict[str, Any]:
    """Capture scalars before provider/DB work; never inspect ORM state after a failed commit."""
    parameters = check_run.run_parameters or {}
    context = {
        "app_release_sha": _release_sha(),
        "check_run_id": str(check_run.id),
        "analysis_id": str(check_run.analysis_id),
        "document_id": str(document_id) if document_id else None,
        "step_id": str(step_id) if step_id else None,
        "skill_id": str(check_run.skill_id),
        "skill_version": check_run.skill_version,
        "provider": check_run.provider,
        "model": check_run.model,
        "source_snapshot_id": parameters.get("source_snapshot_id"),
        "source_revision": parameters.get("source_revision"),
        "source_fingerprint": parameters.get("source_fingerprint"),
    }
    try:
        job = get_current_job()
        if job is not None:
            context["rq_job_id"] = job.id
            context["rq_retries_left"] = job.retries_left
            context["rq_retry_count"] = getattr(job, "retry_count", None)
    except Exception:
        # Missing queue metadata must never affect an analysis or hide its original failure.
        pass
    return _safe_context(context)


def _release_sha() -> str:
    image_tag = os.environ.get("APP_RELEASE_IMAGE", "").rpartition(":")[2]
    return image_tag if re.fullmatch(r"[0-9a-f]{40}", image_tag) else "unknown"


def log_ic_review_error_diagnostics(diagnostic: dict[str, Any]) -> None:
    # RQ's default formatter drops LogRecord.extra; include the safe JSON in the message.
    try:
        worker_logger.warning("ic_review_diagnostic %s", json.dumps(diagnostic, ensure_ascii=True, sort_keys=True))
    except Exception:
        pass


def _identifier(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,159}", value):
        return value
    return None


def _safe_context(context: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "app_release_sha", "check_run_id", "analysis_id", "document_id", "step_id",
        "skill_id", "skill_version", "provider", "model", "source_snapshot_id",
        "source_revision", "source_fingerprint", "rq_job_id", "operation",
    }
    safe = {key: _identifier(context.get(key)) for key in allowed if key in context}
    for key in ("rq_retries_left", "rq_retry_count"):
        value = context.get(key)
        if type(value) is int and value >= 0:
            safe[key] = value
    return safe


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    while exc is not None and all(exc is not previous for previous in chain) and len(chain) < 8:
        chain.append(exc)
        exc = exc.__cause__ or exc.__context__
    return chain


def _validation_details(exc: ValidationError, schema: dict[str, Any]) -> dict[str, Any]:
    # Only contract-defined names may enter a path; dynamic object keys can contain PII.
    names: set[str] = set()
    keywords: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            keywords.update(node)
            for key, value in node.items():
                if key in {"properties", "$defs", "definitions"} and isinstance(value, dict):
                    names.update(value)
                if isinstance(value, (dict, list)):
                    collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(schema)

    def path(parts: Any, allowed: set[str]) -> list[str | int]:
        return [part if type(part) is int or part in allowed else "<dynamic>" for part in list(parts)[:32]]

    value = exc.instance
    actual_type = (
        "null" if value is None else "boolean" if isinstance(value, bool) else
        "string" if isinstance(value, str) else "object" if isinstance(value, dict) else
        "array" if isinstance(value, list) else "integer" if isinstance(value, int) else
        "number" if isinstance(value, float) else "unknown"
    )
    details: dict[str, Any] = {
        "path": path(exc.absolute_path, names),
        "schema_path": path(exc.absolute_schema_path, names | keywords),
        "validator": _identifier(exc.validator),
        "actual_type": actual_type,
    }
    if isinstance(value, (str, list, dict)):
        details["actual_length"] = len(value)
    expected = exc.validator_value
    if exc.validator in {"minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties",
                         "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}:
        if type(expected) in (int, float):
            details["expected"] = expected
    elif exc.validator == "type":
        types = expected if isinstance(expected, list) else [expected]
        details["expected_types"] = [t for t in types if t in {"string", "object", "array", "null", "boolean", "integer", "number"}]
    elif exc.validator == "required" and isinstance(expected, list) and isinstance(value, dict):
        details["missing_fields"] = [key for key in expected if key in names and key not in value][:32]
    elif exc.validator == "enum" and isinstance(expected, list):
        details["allowed_value_count"] = len(expected)
    return details


def append_ic_review_error_diagnostics(
    run_parameters: dict[str, Any] | None,
    diagnostic: dict[str, Any],
    *,
    limit: int = 10,
) -> dict[str, Any]:
    updated = dict(run_parameters or {})
    existing = updated.get(ERROR_DIAGNOSTICS_RUN_PARAMETER_KEY)
    diagnostics = [item for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
    diagnostics.append(diagnostic)
    updated[ERROR_DIAGNOSTICS_RUN_PARAMETER_KEY] = diagnostics[-limit:]
    return updated


def _safe_traceback(exc: BaseException) -> list[dict[str, Any]]:
    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ is not None else []
    return [
        {
            "file": Path(frame.filename).name,
            "function": frame.name,
            "line": frame.lineno,
        }
        for frame in frames[-8:]
    ]


def _safe_db_error_details(exc: BaseException) -> dict[str, Any] | None:
    if not isinstance(exc, DBAPIError):
        return None
    details: dict[str, Any] = {
        "statement_operation": _statement_operation(exc.statement),
        "dbapi_error_class": exc.orig.__class__.__name__ if exc.orig is not None else None,
        "dbapi_error_module": exc.orig.__class__.__module__ if exc.orig is not None else None,
    }
    sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
    if sqlstate:
        details["sqlstate"] = str(sqlstate)
    return {key: value for key, value in details.items() if value}


def _statement_operation(statement: str | None) -> str | None:
    if not statement:
        return None
    match = re.match(r"\s*([A-Za-z]+)", statement)
    return match.group(1).upper() if match else None

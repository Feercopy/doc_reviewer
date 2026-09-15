from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import traceback
from typing import Any

from jsonschema import ValidationError


class IcReviewRunCancelled(RuntimeError):
    pass


ERROR_DIAGNOSTICS_RUN_PARAMETER_KEY = "ic_review_error_diagnostics"

SAFE_ERROR_CODES = {
    "formula_auditor_failed",
    "ic_review_artifact_path_escapes_run_dir",
    "ic_review_context_missing",
    "ic_review_document_missing",
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
) -> dict[str, Any]:
    message = str(exc)
    diagnostic: dict[str, Any] = {
        "version": 1,
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
    return diagnostic


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

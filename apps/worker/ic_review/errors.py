from __future__ import annotations

import json
import re

from jsonschema import ValidationError


class IcReviewRunCancelled(RuntimeError):
    pass


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

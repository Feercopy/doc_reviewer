from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest
import httpx
from jsonschema import ValidationError, validate
from openai import APIConnectionError, APIStatusError
from sqlalchemy.exc import ProgrammingError

from ic_review.errors import (
    append_ic_review_error_diagnostics,
    build_ic_review_error_diagnostics,
    build_ic_review_provider_attempt,
    ic_review_diagnostic_context,
    log_ic_review_error_diagnostics,
    log_ic_review_provider_attempt,
    safe_ic_review_error_message,
)
import ic_review.errors as errors


class DuplicatePreparedStatement(Exception):
    pass


def test_unknown_exception_message_is_not_returned_verbatim():
    message = safe_ic_review_error_message(RuntimeError("SECRET_DOCUMENT_EVIDENCE_SHOULD_NOT_RENDER"))

    assert message == "runtime_error"
    assert "SECRET_DOCUMENT_EVIDENCE_SHOULD_NOT_RENDER" not in message


def test_known_internal_error_code_is_preserved():
    assert safe_ic_review_error_message(RuntimeError("provider_key_missing")) == "provider_key_missing"
    assert safe_ic_review_error_message(RuntimeError("unsupported_ic_role:not-a-role")) == "unsupported_ic_role:not-a-role"


def test_validation_and_json_errors_are_sanitized_without_instances():
    validation_error = ValidationError("not one of ['ic-product-analyst']", validator="enum")
    json_error = json.JSONDecodeError("Expecting value", "not-json", 0)

    assert safe_ic_review_error_message(validation_error) == "schema_validation_failed:enum"
    assert safe_ic_review_error_message(json_error) == "invalid_json:Expecting value"


def test_duplicate_prepared_statement_is_reported_as_safe_db_code():
    error = ProgrammingError(
        "INSERT INTO analysis_check_steps ...",
        {},
        DuplicatePreparedStatement("prepared statement already exists"),
    )

    assert safe_ic_review_error_message(error) == "duplicate_prepared_statement"

    diagnostic = build_ic_review_error_diagnostics(
        error,
        phase="role_step",
        stage="role:ic-financial-auditor",
        step_name="ic-financial-auditor",
    )

    assert diagnostic["code"] == "duplicate_prepared_statement"
    assert diagnostic["db_error"] == {
        "statement_operation": "INSERT",
        "dbapi_error_class": "DuplicatePreparedStatement",
        "dbapi_error_module": __name__,
    }
    assert "prepared statement already exists" not in json.dumps(diagnostic)


def test_nested_schema_error_reports_field_constraint_and_length_not_value():
    schema = {"type": "object", "properties": {
        "findings": {"type": "array", "items": {"type": "object", "properties": {
            "evidence": {"type": "string", "minLength": 100},
        }}},
    }}
    private_text = "PRIVATE_EVIDENCE"
    with pytest.raises(ValidationError) as raised:
        validate({"findings": [{"evidence": private_text}]}, schema)
    wrapper = RuntimeError("invalid synthesis with private response")
    wrapper.__cause__ = raised.value
    outer = RuntimeError("outer error")
    outer.__cause__ = wrapper
    diagnostic = build_ic_review_error_diagnostics(
        outer, phase="job_failure", stage="synthesis", schema=schema, schema_name="ic-result.schema.json",
    )
    assert diagnostic["validation"] == {
        "path": ["findings", 0, "evidence"],
        "schema_path": ["properties", "findings", "items", "properties", "evidence", "minLength"],
        "validator": "minLength", "actual_type": "string", "actual_length": len(private_text), "expected": 100,
    }
    assert diagnostic["schema"]["name"] == "ic-result.schema.json"
    assert len(diagnostic["schema"]["sha256"]) == 64
    assert private_text not in json.dumps(diagnostic)
    assert "private response" not in json.dumps(diagnostic)
    changed = build_ic_review_error_diagnostics(
        outer, phase="job_failure", stage="synthesis", schema={**schema, "required": ["findings"]},
    )
    assert diagnostic["schema"]["sha256"] != changed["schema"]["sha256"]


def test_dynamic_object_keys_and_values_are_not_logged():
    schema = {"type": "object", "additionalProperties": {"type": "string", "minLength": 100}}
    with pytest.raises(ValidationError) as raised:
        validate({"PRIVATE_PERSON_NAME": "PRIVATE_EVIDENCE"}, schema)
    diagnostic = build_ic_review_error_diagnostics(raised.value, phase="role_step", stage="role", schema=schema)
    assert diagnostic["validation"]["path"] == ["<dynamic>"]
    assert "PRIVATE_" not in json.dumps(diagnostic)


def test_required_fields_report_missing_names_not_present_values():
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}
    with pytest.raises(ValidationError) as raised:
        validate({"untrusted": "PRIVATE_EVIDENCE"}, schema)
    diagnostic = build_ic_review_error_diagnostics(raised.value, phase="role_step", stage="role", schema=schema)
    assert diagnostic["validation"]["missing_fields"] == ["summary"]
    assert "PRIVATE_EVIDENCE" not in json.dumps(diagnostic)


def test_json_location_and_provider_status_are_safe_even_in_wrapped_errors():
    error = RuntimeError("PRIVATE_RESPONSE")
    error.status_code = 429
    error.request_id = "req-123"
    error.body = {"message": "PRIVATE_BODY"}
    error.__cause__ = json.JSONDecodeError("Expecting value", "PRIVATE_DOCUMENT", 4)
    diagnostic = build_ic_review_error_diagnostics(error, phase="role_step", stage="role")
    assert diagnostic["provider_error"] == {"status_code": 429, "request_id": "req-123"}
    assert diagnostic["json_error"] == {"line": 1, "column": 5, "position": 4}
    assert "PRIVATE_" not in json.dumps(diagnostic)


def test_provider_attempts_capture_safe_http_and_transport_metadata(caplog):
    response = httpx.Response(
        503,
        request=httpx.Request("POST", "https://provider.test/v1?secret=PRIVATE_TOKEN"),
        headers={"x-request-id": "req-503", "authorization": "PRIVATE_KEY"},
        json={"message": "PRIVATE_DOCUMENT"},
    )
    status_error = APIStatusError("PRIVATE_RESPONSE", response=response, body={"private": "PRIVATE_BODY"})
    failed = build_ic_review_provider_attempt(attempt=1, elapsed_ms=42, error=status_error)
    assert failed["http_status"] == 503
    assert failed["request_id"] == "req-503"

    connection_error = APIConnectionError(request=httpx.Request("POST", "https://provider.test/v1"))
    connection_error.__cause__ = httpx.RemoteProtocolError("PRIVATE_RESPONSE")
    disconnected = build_ic_review_provider_attempt(
        attempt=2, elapsed_ms=43, error=connection_error, retry_delay_ms=500,
    )
    assert disconnected["http_status"] is None
    assert disconnected["request_id"] is None
    assert disconnected["transport_error_class"] == "RemoteProtocolError"
    direct_transport_error = build_ic_review_provider_attempt(
        attempt=3, elapsed_ms=44, error=httpx.RemoteProtocolError("PRIVATE_RESPONSE"),
    )
    assert direct_transport_error["transport_error_class"] == "RemoteProtocolError"
    diagnostic = build_ic_review_error_diagnostics(
        connection_error, phase="role_step", stage="role:ic-financial-auditor",
        provider_attempts=[failed, disconnected],
    )
    assert diagnostic["provider_attempts"] == [failed, disconnected]
    with caplog.at_level(logging.INFO, logger="gate_challenger.worker"):
        log_ic_review_provider_attempt(
            context={"check_run_id": "run-1", "api_key": "PRIVATE_KEY"},
            role="ic-financial-auditor", attempt=failed,
            prompt_sha256="a" * 64, prompt_chars=200,
            timeout_seconds=300, connect_timeout_seconds=30,
        )
    logged = json.loads(caplog.records[-1].getMessage().removeprefix("ic_review_provider_attempt "))
    assert logged["request_id"] == "req-503"
    assert logged["context"] == {"check_run_id": "run-1"}
    assert "PRIVATE_" not in caplog.text
    assert "PRIVATE_" not in json.dumps(diagnostic)


def test_run_context_is_allowlisted_and_includes_release_snapshot_and_queue(monkeypatch):
    monkeypatch.setenv("APP_RELEASE_IMAGE", "gate-challenger-worker:" + "a" * 40)
    monkeypatch.setattr(errors, "get_current_job", lambda: SimpleNamespace(id="job-1", retries_left=2, retry_count=1))
    run = SimpleNamespace(
        id=uuid4(), analysis_id=uuid4(), skill_id=uuid4(), skill_version="v2", provider="openai_compatible",
        model="anthropic/claude-test", run_parameters={
            "source_snapshot_id": str(uuid4()), "source_revision": "b" * 40, "source_fingerprint": "c" * 64,
            "api_key": "PRIVATE_KEY", "source_snapshot_artifact_path": "/private/storage/path",
            "model_anonymization": {"replacements": {"PRIVATE_NAME": "PERSON_1"}},
        },
    )
    document_id, step_id = uuid4(), uuid4()
    context = ic_review_diagnostic_context(run, document_id=document_id, step_id=step_id)
    assert context["app_release_sha"] == "a" * 40
    assert context["check_run_id"] == str(run.id)
    assert context["analysis_id"] == str(run.analysis_id)
    assert context["document_id"] == str(document_id)
    assert context["step_id"] == str(step_id)
    assert context["skill_version"] == "v2"
    assert context["source_fingerprint"] == "c" * 64
    assert context["rq_job_id"] == "job-1"
    assert context["rq_retries_left"] == 2
    assert context["rq_retry_count"] == 1
    assert "PRIVATE_" not in json.dumps(context)
    assert "/private/storage" not in json.dumps(context)
    monkeypatch.delenv("APP_RELEASE_IMAGE")
    monkeypatch.setattr(errors, "get_current_job", lambda: (_ for _ in ()).throw(RuntimeError("queue unavailable")))
    context = ic_review_diagnostic_context(run)
    assert context["app_release_sha"] == "unknown"
    assert "rq_job_id" not in context


def test_diagnostics_log_json_without_extra_formatter_and_remain_bounded(caplog, monkeypatch):
    diagnostic = build_ic_review_error_diagnostics(
        RuntimeError("PRIVATE_MESSAGE"), phase="job_failure", stage="synthesis", elapsed_ms=123,
        context={"check_run_id": "run-1", "raw_output": "PRIVATE_OUTPUT", "model": "bad\nPRIVATE_KEY"},
    )
    log_ic_review_error_diagnostics(diagnostic)
    payload = json.loads(caplog.records[-1].getMessage().removeprefix("ic_review_diagnostic "))
    assert payload["elapsed_ms"] == 123
    assert payload["context"]["check_run_id"] == "run-1"
    assert "PRIVATE_" not in caplog.text
    parameters = {"ic_review_error_diagnostics": [diagnostic] * 10, "other": True}
    updated = append_ic_review_error_diagnostics(parameters, diagnostic)
    assert len(updated["ic_review_error_diagnostics"]) == 10
    assert updated["other"] is True
    monkeypatch.setattr(errors.worker_logger, "warning", lambda *_args: (_ for _ in ()).throw(OSError()))
    log_ic_review_error_diagnostics(diagnostic)

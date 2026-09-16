from __future__ import annotations

import json

from jsonschema import ValidationError
from sqlalchemy.exc import ProgrammingError

from ic_review.errors import build_ic_review_error_diagnostics, safe_ic_review_error_message


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

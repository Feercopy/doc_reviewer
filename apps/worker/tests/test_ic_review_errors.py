from __future__ import annotations

import json

from jsonschema import ValidationError

from ic_review.errors import safe_ic_review_error_message


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

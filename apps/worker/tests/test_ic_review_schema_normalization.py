from __future__ import annotations

from jsonschema import validate

from ic_review.schema_normalization import normalize_schema_bounded_strings


def test_normalizes_empty_required_strings_inside_nested_objects():
    schema = {
        "type": "object",
        "required": ["summary", "finding"],
        "properties": {
            "summary": {"type": "string", "minLength": 1, "maxLength": 80},
            "finding": {
                "type": "object",
                "required": ["evidence"],
                "properties": {
                    "evidence": {"type": "string", "minLength": 1, "maxLength": 80},
                },
            },
        },
    }

    normalized = normalize_schema_bounded_strings(
        {"summary": "   ", "finding": {"evidence": ""}},
        schema,
        schema,
    )

    validate(instance=normalized, schema=schema)
    assert normalized["summary"] == "Not provided in source materials."
    assert normalized["finding"]["evidence"] == "Not provided in source materials."


def test_extends_short_strings_to_schema_min_length_without_exceeding_max_length():
    schema = {
        "type": "object",
        "required": ["executive_brief"],
        "properties": {
            "executive_brief": {"type": "string", "minLength": 120, "maxLength": 140},
        },
    }

    normalized = normalize_schema_bounded_strings({"executive_brief": "Too short."}, schema, schema)

    validate(instance=normalized, schema=schema)
    assert len(normalized["executive_brief"]) >= 120
    assert len(normalized["executive_brief"]) <= 140


def test_keeps_enum_and_const_values_strict():
    schema = {
        "type": "object",
        "required": ["role", "run_mode"],
        "properties": {
            "role": {"type": "string", "enum": ["ic-product-analyst"]},
            "run_mode": {"type": "string", "const": "ic_agentic_review_compact"},
        },
    }

    normalized = normalize_schema_bounded_strings({"role": "", "run_mode": ""}, schema, schema)

    assert normalized == {"role": "", "run_mode": ""}


def test_still_trims_overlong_strings():
    schema = {
        "type": "object",
        "required": ["summary"],
        "properties": {
            "summary": {"type": "string", "minLength": 1, "maxLength": 5},
        },
    }

    normalized = normalize_schema_bounded_strings({"summary": "abcdef"}, schema, schema)

    validate(instance=normalized, schema=schema)
    assert normalized["summary"] == "abcde"

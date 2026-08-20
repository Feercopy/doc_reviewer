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
                "required": ["detail"],
                "properties": {
                    "detail": {"type": "string", "minLength": 1, "maxLength": 80},
                },
            },
        },
    }

    normalized = normalize_schema_bounded_strings(
        {"summary": "   ", "finding": {"detail": ""}},
        schema,
        schema,
    )

    validate(instance=normalized, schema=schema)
    assert normalized["summary"] == "Not provided in source materials."
    assert normalized["finding"]["detail"] == "Not provided in source materials."


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
    assert normalized["executive_brief"].startswith("Too short.")
    assert len(normalized["executive_brief"]) >= 120
    assert len(normalized["executive_brief"]) <= 140


def test_uses_russian_source_gap_marker_for_russian_reviews():
    schema = {
        "type": "object",
        "required": ["summary"],
        "properties": {
            "summary": {"type": "string", "minLength": 40, "maxLength": 120},
        },
    }

    normalized = normalize_schema_bounded_strings(
        {"summary": ""},
        schema,
        schema,
        output_language="ru",
    )

    validate(instance=normalized, schema=schema)
    assert normalized["summary"].startswith("Не указано в исходных материалах.")


def test_drops_empty_reference_ids_instead_of_fabricating_evidence():
    schema = {
        "type": "object",
        "required": ["evidence_ids"],
        "properties": {
            "evidence_ids": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 80},
            },
        },
    }

    normalized = normalize_schema_bounded_strings(
        {"evidence_ids": ["doc-1", " ", ""]},
        schema,
        schema,
    )

    validate(instance=normalized, schema=schema)
    assert normalized["evidence_ids"] == ["doc-1"]


def test_drops_findings_without_evidence_instead_of_fabricating_evidence():
    schema = {
        "type": "object",
        "required": ["findings"],
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["title", "severity", "evidence", "recommendation"],
                    "properties": {
                        "title": {"type": "string", "minLength": 1, "maxLength": 80},
                        "severity": {"type": "string", "enum": ["critical", "data_gap"]},
                        "evidence": {"type": "string", "minLength": 1, "maxLength": 120},
                        "recommendation": {"type": "string", "minLength": 1, "maxLength": 120},
                    },
                },
            },
        },
    }

    normalized = normalize_schema_bounded_strings(
        {
            "findings": [
                {
                    "title": "Missing proof",
                    "severity": "critical",
                    "evidence": "",
                    "recommendation": "Close the gap.",
                },
                {
                    "title": "Measured proof",
                    "severity": "critical",
                    "evidence": "Document page 4 contains measured proof.",
                    "recommendation": "Keep the proof in the package.",
                },
            ]
        },
        schema,
        schema,
    )

    validate(instance=normalized, schema=schema)
    assert len(normalized["findings"]) == 1
    assert normalized["findings"][0]["title"] == "Measured proof"


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

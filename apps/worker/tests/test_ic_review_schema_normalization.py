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


def test_reconciles_compact_verdict_when_all_top_findings_lack_evidence():
    schema = {
        "type": "object",
        "required": ["verdict", "confidence", "top_findings", "data_gaps"],
        "properties": {
            "verdict": {"type": "string", "enum": ["NO-GO", "UNKNOWN"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "top_findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["title", "severity", "summary", "evidence", "recommendation"],
                    "properties": {
                        "title": {"type": "string", "minLength": 1, "maxLength": 80},
                        "severity": {"type": "string", "enum": ["critical", "data_gap"]},
                        "summary": {"type": "string", "minLength": 1, "maxLength": 120},
                        "evidence": {"type": "string", "minLength": 1, "maxLength": 120},
                        "recommendation": {"type": "string", "minLength": 1, "maxLength": 120},
                    },
                },
            },
            "data_gaps": {
                "type": "array",
                "maxItems": 7,
                "items": {"type": "string", "minLength": 1, "maxLength": 200},
            },
        },
    }

    normalized = normalize_schema_bounded_strings(
        {
            "verdict": "NO-GO",
            "confidence": 0.8,
            "top_findings": [
                {
                    "title": "Missing proof",
                    "severity": "critical",
                    "summary": "The claim is not supported.",
                    "evidence": "",
                    "recommendation": "Do not approve.",
                }
            ],
            "data_gaps": [],
        },
        schema,
        schema,
        output_language="ru",
    )

    validate(instance=normalized, schema=schema)
    assert normalized["verdict"] == "UNKNOWN"
    assert normalized["confidence"] == 0.1
    assert normalized["top_findings"] == []
    assert normalized["data_gaps"] == [
        "Неподтвержденные выводы IC Review отброшены: в них не было evidence."
    ]


def test_drops_numbers_without_source_instead_of_fabricating_provenance():
    schema = {
        "type": "object",
        "required": ["numbers_used"],
        "properties": {
            "numbers_used": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["label", "value", "source"],
                    "properties": {
                        "label": {"type": "string", "minLength": 1, "maxLength": 80},
                        "value": {"type": "string", "minLength": 1, "maxLength": 80},
                        "source": {"type": "string", "minLength": 1, "maxLength": 120},
                    },
                },
            },
        },
    }

    normalized = normalize_schema_bounded_strings(
        {
            "numbers_used": [
                {"label": "Revenue", "value": "10", "source": ""},
                {"label": "GMV", "value": "20", "source": "Financial model sheet 2"},
            ]
        },
        schema,
        schema,
    )

    validate(instance=normalized, schema=schema)
    assert normalized["numbers_used"] == [
        {"label": "GMV", "value": "20", "source": "Financial model sheet 2"}
    ]


def test_drops_blank_categorical_list_items_instead_of_fabricating_risks():
    schema = {
        "type": "object",
        "required": ["critical_risks"],
        "properties": {
            "critical_risks": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 120},
            },
        },
    }

    normalized = normalize_schema_bounded_strings(
        {"critical_risks": [" ", "Margin sensitivity is not quantified."]},
        schema,
        schema,
    )

    validate(instance=normalized, schema=schema)
    assert normalized["critical_risks"] == ["Margin sensitivity is not quantified."]


def test_drops_blank_report_items_instead_of_fabricating_structured_risks():
    schema = {
        "type": "object",
        "required": ["risks"],
        "properties": {
            "risks": {
                "type": "array",
                "items": {"$ref": "#/$defs/report_item"},
            },
        },
        "$defs": {
            "report_item": {
                "type": "object",
                "required": ["title", "detail"],
                "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 80},
                    "detail": {"type": "string", "minLength": 1, "maxLength": 120},
                    "severity": {"type": "string", "maxLength": 80},
                },
            },
        },
    }

    normalized = normalize_schema_bounded_strings(
        {
            "risks": [
                {"title": "", "detail": "", "severity": "critical"},
                {
                    "title": "Margin sensitivity",
                    "detail": "Downside scenario is not quantified.",
                    "severity": "critical",
                },
            ]
        },
        schema,
        schema,
    )

    validate(instance=normalized, schema=schema)
    assert normalized["risks"] == [
        {
            "title": "Margin sensitivity",
            "detail": "Downside scenario is not quantified.",
            "severity": "critical",
        }
    ]


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

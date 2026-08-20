from __future__ import annotations

from typing import Any


_NARRATIVE_STRING_PROPERTIES = {
    "body",
    "comment",
    "content",
    "critical_risks",
    "data_gaps",
    "detail",
    "executive_brief",
    "issue",
    "markdown",
    "primary_verify_notes",
    "questions_for_team",
    "recommendation",
    "required_actions",
    "summary",
    "title",
}
_REFERENCE_ARRAY_PROPERTIES = {"evidence_ids", "section_keys"}
_FINDING_ARRAY_PROPERTIES = {"findings", "top_findings"}
_NUMBER_ARRAY_PROPERTIES = {"key_numbers", "numbers_used"}
_CATEGORICAL_TEXT_ARRAY_PROPERTIES = {
    "critical_risks",
    "data_gaps",
    "primary_verify_notes",
    "questions_for_team",
    "required_actions",
}


def normalize_schema_bounded_strings(
    value: Any,
    schema: dict,
    root_schema: dict,
    *,
    output_language: str | None = None,
) -> Any:
    return _normalize_schema_bounded_strings(
        value,
        schema,
        root_schema,
        property_name=None,
        output_language=output_language,
    )


def _normalize_schema_bounded_strings(
    value: Any,
    schema: dict,
    root_schema: dict,
    *,
    property_name: str | None,
    output_language: str | None,
) -> Any:
    resolved_schema = schema
    if "$ref" in resolved_schema:
        resolved = _resolve_local_schema_ref(str(resolved_schema["$ref"]), root_schema)
        if resolved is not None:
            resolved_schema = resolved

    for combinator in ("anyOf", "oneOf"):
        options = resolved_schema.get(combinator)
        if isinstance(options, list):
            for option in options:
                if isinstance(option, dict) and _schema_option_matches_value(option, value, root_schema):
                    return _normalize_schema_bounded_strings(
                        value,
                        option,
                        root_schema,
                        property_name=property_name,
                        output_language=output_language,
                    )
            return value

    all_of = resolved_schema.get("allOf")
    if isinstance(all_of, list):
        normalized = value
        for option in all_of:
            if isinstance(option, dict):
                normalized = _normalize_schema_bounded_strings(
                    normalized,
                    option,
                    root_schema,
                    property_name=property_name,
                    output_language=output_language,
                )
        return normalized

    expected_type = resolved_schema.get("type")
    if expected_type == "string" and isinstance(value, str):
        if "const" in resolved_schema or "enum" in resolved_schema:
            return value
        normalized = value.strip()
        min_length = resolved_schema.get("minLength")
        max_length = resolved_schema.get("maxLength")
        if (
            isinstance(min_length, int)
            and len(normalized) < min_length
            and property_name in _NARRATIVE_STRING_PROPERTIES
        ):
            normalized = _min_length_fallback(
                value=normalized,
                min_length=min_length,
                max_length=max_length if isinstance(max_length, int) else None,
                output_language=output_language,
            )
        if isinstance(max_length, int) and len(normalized) > max_length:
            return normalized[:max_length]
        return normalized

    if expected_type == "object" and isinstance(value, dict):
        properties = resolved_schema.get("properties")
        if not isinstance(properties, dict):
            return value
        normalized = dict(value)
        for key, child_schema in properties.items():
            if key in normalized and isinstance(child_schema, dict):
                normalized[key] = _normalize_schema_bounded_strings(
                    normalized[key],
                    child_schema,
                    root_schema,
                    property_name=key,
                    output_language=output_language,
                )
        return normalized

    if expected_type == "array" and isinstance(value, list):
        item_schema = resolved_schema.get("items")
        normalized_items = value
        if _array_items_are_report_items(item_schema, root_schema):
            normalized_items = [
                item for item in value if not _report_item_lacks_substance(item)
            ]
        elif property_name in _REFERENCE_ARRAY_PROPERTIES:
            normalized_items = [
                item for item in value if not (isinstance(item, str) and not item.strip())
            ]
        elif property_name in _FINDING_ARRAY_PROPERTIES:
            normalized_items = [
                item for item in value if not _finding_lacks_evidence(item)
            ]
        elif property_name in _NUMBER_ARRAY_PROPERTIES:
            normalized_items = [
                item for item in value if not _number_lacks_source(item)
            ]
        elif property_name in _CATEGORICAL_TEXT_ARRAY_PROPERTIES:
            normalized_items = [
                item for item in value if not (isinstance(item, str) and not item.strip())
            ]
        if isinstance(item_schema, dict):
            item_property_name = (
                None if property_name in _CATEGORICAL_TEXT_ARRAY_PROPERTIES else property_name
            )
            return [
                _normalize_schema_bounded_strings(
                    item,
                    item_schema,
                    root_schema,
                    property_name=item_property_name,
                    output_language=output_language,
                )
                for item in normalized_items
            ]
        return normalized_items

    return value


def _min_length_fallback(
    *,
    value: str,
    min_length: int,
    max_length: int | None,
    output_language: str | None,
) -> str:
    marker = _source_gap_marker(output_language)
    if value:
        base = f"{value} [{marker}]"
    else:
        base = marker
    if max_length is not None and max_length < len(base):
        return base[:max(max_length, 0)]
    if min_length <= len(base):
        return base
    target_length = min_length
    if max_length is not None:
        target_length = min(min_length, max_length)
    parts = []
    while len(" ".join(parts)) < target_length:
        parts.append(base if not parts else marker)
    return " ".join(parts)[:target_length]


def _source_gap_marker(output_language: str | None) -> str:
    if str(output_language or "").lower().startswith("ru"):
        return "Не указано в исходных материалах."
    return "Not provided in source materials."


def _finding_lacks_evidence(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    evidence = item.get("evidence")
    return isinstance(evidence, str) and not evidence.strip()


def _number_lacks_source(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    source = item.get("source")
    return isinstance(source, str) and not source.strip()


def _report_item_lacks_substance(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    title = item.get("title")
    detail = item.get("detail")
    return (
        isinstance(title, str)
        and not title.strip()
        and isinstance(detail, str)
        and not detail.strip()
    )


def _array_items_are_report_items(item_schema: Any, root_schema: dict) -> bool:
    if not isinstance(item_schema, dict):
        return False
    resolved_schema = item_schema
    if "$ref" in resolved_schema:
        resolved = _resolve_local_schema_ref(str(resolved_schema["$ref"]), root_schema)
        if resolved is not None:
            resolved_schema = resolved
    properties = resolved_schema.get("properties")
    required = resolved_schema.get("required")
    return (
        resolved_schema.get("type") == "object"
        and isinstance(properties, dict)
        and isinstance(required, list)
        and {"title", "detail"}.issubset(set(required))
        and {"title", "detail"}.issubset(properties)
    )


def _schema_option_matches_value(schema: dict, value: Any, root_schema: dict) -> bool:
    if "$ref" in schema:
        resolved = _resolve_local_schema_ref(str(schema["$ref"]), root_schema)
        if resolved is not None:
            return _schema_option_matches_value(resolved, value, root_schema)

    expected_type = schema.get("type")
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "null":
        return value is None
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return True


def _resolve_local_schema_ref(ref: str, root_schema: dict) -> dict | None:
    if not ref.startswith("#/"):
        return None
    current: Any = root_schema
    for raw_part in ref.removeprefix("#/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current if isinstance(current, dict) else None

from __future__ import annotations

from typing import Any


def normalize_schema_bounded_strings(value: Any, schema: dict, root_schema: dict) -> Any:
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
                    return normalize_schema_bounded_strings(value, option, root_schema)
            return value

    all_of = resolved_schema.get("allOf")
    if isinstance(all_of, list):
        normalized = value
        for option in all_of:
            if isinstance(option, dict):
                normalized = normalize_schema_bounded_strings(normalized, option, root_schema)
        return normalized

    expected_type = resolved_schema.get("type")
    if expected_type == "string" and isinstance(value, str):
        max_length = resolved_schema.get("maxLength")
        if isinstance(max_length, int) and len(value) > max_length:
            return value[:max_length]
        return value

    if expected_type == "object" and isinstance(value, dict):
        properties = resolved_schema.get("properties")
        if not isinstance(properties, dict):
            return value
        normalized = dict(value)
        for key, child_schema in properties.items():
            if key in normalized and isinstance(child_schema, dict):
                normalized[key] = normalize_schema_bounded_strings(normalized[key], child_schema, root_schema)
        return normalized

    if expected_type == "array" and isinstance(value, list):
        item_schema = resolved_schema.get("items")
        if isinstance(item_schema, dict):
            return [normalize_schema_bounded_strings(item, item_schema, root_schema) for item in value]
        return value

    return value


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

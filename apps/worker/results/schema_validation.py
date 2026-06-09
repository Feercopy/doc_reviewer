import json
import re
from pathlib import Path

from jsonschema import validate


FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def parse_and_validate_json_output(*, structured_text: str, schema_path: str) -> dict:
    payload = json.loads(_extract_json_text(structured_text))
    schema = json.loads(_resolve_schema_path(schema_path).read_text(encoding="utf-8"))
    validate(instance=payload, schema=schema)
    return payload


def _extract_json_text(structured_text: str) -> str:
    stripped = structured_text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped
    match = FENCED_JSON_RE.search(stripped)
    if match:
        return match.group(1).strip()
    return structured_text


def _resolve_schema_path(schema_path: str) -> Path:
    root = Path(__file__).resolve().parents[3]
    return root / schema_path

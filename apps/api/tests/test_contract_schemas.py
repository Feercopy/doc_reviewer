import json
from pathlib import Path

from jsonschema import ValidationError, validate


SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "contracts" / "schemas"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text())


def test_main_analysis_schema_accepts_valid_result():
    schema = load_schema("main-analysis-result.schema.json")
    payload = {
        "verdict": "need_evidence",
        "summary": "Evidence is incomplete.",
        "findings": [
            {
                "id": "finding-1",
                "severity": "high",
                "title": "No benchmark baseline",
                "evidence": "Document does not show a baseline.",
            }
        ],
        "checks": [{"name": "Evidence", "status": "partial"}],
    }

    validate(instance=payload, schema=schema)


def test_main_analysis_schema_rejects_unknown_verdict():
    schema = load_schema("main-analysis-result.schema.json")
    payload = {
        "verdict": "ship_it",
        "summary": "Invalid.",
        "findings": [],
        "checks": [],
    }

    try:
        validate(instance=payload, schema=schema)
    except ValidationError:
        return

    raise AssertionError("schema accepted an unsupported verdict")

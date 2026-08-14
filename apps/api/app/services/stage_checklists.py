from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def _stage_checklist_items_by_document_type() -> dict[str, list[dict[str, str]]]:
    path = _stage_checklist_contract_path()
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_object_without_duplicate_keys,
    )
    return value if isinstance(value, dict) else {}


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate key in stage checklist contract: {key}")
        value[key] = item
    return value


def _stage_checklist_contract_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts" / "stage-checklists.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("contracts/stage-checklists.json")


def stage_checklist_items(document_type: str | None, *, output_language: str = "ru") -> list[tuple[str, str]]:
    language_key = "label_en" if output_language == "en" else "label_ru"
    return [
        (item["id"], item[language_key])
        for item in _stage_checklist_items_by_document_type().get(str(document_type or ""), [])
    ]


def canonical_stage_checklist_label(item_id: Any, *, output_language: str) -> str | None:
    if not isinstance(item_id, str):
        return None
    language_key = "label_en" if output_language == "en" else "label_ru"
    for items in _stage_checklist_items_by_document_type().values():
        for item in items:
            if item.get("id") == item_id:
                return item.get(language_key)
    return None


def canonicalize_stage_checklist_labels(payload: dict[str, Any], *, output_language: str) -> dict[str, Any]:
    checklist = payload.get("stage_checklist")
    if not isinstance(checklist, list):
        return payload
    result = dict(payload)
    result["stage_checklist"] = [
        _canonicalized_item(item, output_language=output_language)
        for item in checklist
    ]
    return result


def _canonicalized_item(item: Any, *, output_language: str) -> Any:
    if not isinstance(item, dict):
        return item
    label = canonical_stage_checklist_label(item.get("id"), output_language=output_language)
    return {**item, "label": label} if label else dict(item)

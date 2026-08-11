from typing import Any

from app.services.stage_checklists import stage_checklist_items


def expected_stage_checklist_ids(document_type: str | None) -> list[str]:
    return [item_id for item_id, _label in stage_checklist_items(document_type)]


def validate_stage_checklist_for_document_type(payload: dict[str, Any], *, document_type: str | None) -> None:
    expected_ids = expected_stage_checklist_ids(document_type)
    if not expected_ids:
        return

    checklist = payload.get("stage_checklist")
    if not isinstance(checklist, list):
        raise ValueError("stage_checklist must be an array for Gate Challenger analysis results")

    actual_ids = [
        item.get("id")
        for item in checklist
        if isinstance(item, dict)
    ]
    if actual_ids != expected_ids:
        raise ValueError(
            "stage_checklist must match the selected document type exactly: "
            f"expected ids {expected_ids}, got {actual_ids}"
        )

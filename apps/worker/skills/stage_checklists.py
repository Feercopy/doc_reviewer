from typing import Any


_STAGE_CHECKLIST_ITEMS = {
    "gate_2": [
        {
            "id": "gate2_hypothesis_results",
            "label_ru": "Результаты проверки гипотез из Gate 1",
            "label_en": "Gate 1 hypothesis validation results",
        },
        {
            "id": "gate2_mvp_or_target_product",
            "label_ru": "Описание MVP/целевого продукта",
            "label_en": "MVP or target product description",
        },
        {
            "id": "gate2_mockups_or_user_flow",
            "label_ru": "Mockups или видео пользовательского flow",
            "label_en": "User-flow mockups or video",
        },
        {
            "id": "gate2_gate3_commitments",
            "label_ru": "Commitments к Gate 3: сроки, expected performance, метрики",
            "label_en": "Gate 3 commitments: timeline, expected performance, and metrics",
        },
    ],
    "gate_3": [
        {
            "id": "gate3_working_mvp",
            "label_ru": "Работающий MVP",
            "label_en": "Working MVP",
        },
        {
            "id": "gate3_performance_vs_gate2_plan",
            "label_ru": "Performance/results по сравнению с планом Gate 2",
            "label_en": "Performance/results versus the Gate 2 plan",
        },
        {
            "id": "gate3_pmf_criteria",
            "label_ru": "Критерии product-market fit для следующего review",
            "label_en": "Product-market fit criteria for the next review",
        },
    ],
    "stream_review_1": [
        {
            "id": "stream_review_1_confirmed_problem",
            "label_ru": "Подтвержденная проблематика",
            "label_en": "Confirmed problem",
        },
        {
            "id": "stream_review_1_solution_validation",
            "label_ru": "Подтверждение решения через количественники, прототипы или фейкдоры",
            "label_en": "Solution validation through quantitative tests, prototypes, or fake doors",
        },
        {
            "id": "stream_review_1_half_year_plan_with_metrics",
            "label_ru": "План работ на полгода, включая метрики",
            "label_en": "Six-month work plan with metrics",
        },
    ],
    "stream_review_2_plus": [
        {
            "id": "stream_review_2_plus_plan_fact_last_half_year",
            "label_ru": "План-факт за прошедшие полгода по запускам и метрикам",
            "label_en": "Plan versus actuals for the past six months of launches and metrics",
        },
        {
            "id": "stream_review_2_plus_next_half_year_plan",
            "label_ru": "План на следующие полгода по запускам и метрикам",
            "label_en": "Plan for the next six months of launches and metrics",
        },
    ],
}


def stage_checklist_items(document_type: str | None, *, output_language: str = "ru") -> list[tuple[str, str]]:
    language_key = "label_en" if output_language == "en" else "label_ru"
    return [
        (item["id"], item[language_key])
        for item in _STAGE_CHECKLIST_ITEMS.get(str(document_type or ""), [])
    ]


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

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ICReviewContext:
    document_title: str
    document_type: str
    parsed_document_text: str
    main_analysis_verdict: str | None
    main_analysis_summary: str | None
    main_analysis_structured_output: dict[str, Any] | None
    main_analysis_detail_output: dict[str, Any] | None = None
    workbook_extraction_summary: dict[str, Any] | str | None = None
    formula_auditor_summary: dict[str, Any] | str | None = None
    output_language: str = "ru"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_ic_review_context(
    *,
    document: Any,
    analysis: Any,
    parsed_document_text: str | None = None,
    main_analysis_detail_output: dict[str, Any] | None = None,
    workbook_extraction_summary: dict[str, Any] | str | None = None,
    formula_auditor_summary: dict[str, Any] | str | None = None,
    output_language: str | None = None,
) -> ICReviewContext:
    """Build the serializable role/synthesis context from existing DB records."""
    run_parameters = getattr(analysis, "run_parameters", None) or {}
    document_type = (
        getattr(document, "manual_document_type", None)
        or getattr(document, "detected_document_type", None)
        or "unknown"
    )
    return ICReviewContext(
        document_title=str(getattr(document, "title", "") or ""),
        document_type=str(document_type),
        parsed_document_text=str(parsed_document_text if parsed_document_text is not None else getattr(document, "parsed_text", "") or ""),
        main_analysis_verdict=getattr(analysis, "verdict", None),
        main_analysis_summary=getattr(analysis, "summary", None),
        main_analysis_structured_output=getattr(analysis, "structured_output", None),
        main_analysis_detail_output=main_analysis_detail_output,
        workbook_extraction_summary=workbook_extraction_summary,
        formula_auditor_summary=formula_auditor_summary,
        output_language=str(output_language or run_parameters.get("output_language") or "ru"),
    )

from __future__ import annotations

import hashlib
import json
import re
import traceback
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging import worker_logger
from app.core.config import get_settings
from app.storage.local import LocalDocumentStorage
from app.models.analysis import Analysis, AnalysisCheckRun, AnalysisDetailRun
from app.models.document import Document
from app.schemas.enums import Provider, RunStatus
from app.services.document_type_detector import progress_review_display_stage
from app.services.new_summary_titles import clean_initiative_title, display_new_summary_title
from app.services.new_summary_traction import _period_key, with_traction_totals
from app.services.new_summaries import (
    NEW_SUMMARY_GENERATION_MODE,
    NEW_SUMMARY_VERSION,
    mark_new_summary_cancelled,
    mark_new_summary_failed,
    mark_new_summary_progress,
    mark_new_summary_running,
    persist_new_summary_variant,
    with_summary_display_stage,
)
from ic_review.role_runner import apply_ic_review_provider_defaults
from privacy.model_anonymization import (
    RUN_PARAMETER_KEY,
    anonymize_value_for_model,
    db_safe_anonymization_metadata,
    deanonymize_model_value,
    provider_safe_run_parameters,
)
from providers.base import AnalysisProviderResult, ProviderRunRequest
from providers.registry import get_provider_adapter
from results.schema_validation import parse_json_output
from skills.context_relevance import (
    CONTEXT_CANDIDATE_MARKERS,
    CURRENT_DECISION_MARKERS,
    CURRENT_DEFENSE_MARKERS,
    CURRENT_SCOPE_MARKERS,
    SELECTED_SCENARIO_MARKERS,
    decision_context_score,
)
from skills.result_synthesis_trace import (
    cancel_result_synthesis_step,
    complete_result_synthesis_step,
    fail_result_synthesis_step,
    start_result_synthesis_step,
)
from skills.traction_tables import source_traction_tables
from skills.source_links import pdf_source_links, provider_source_links, safe_source_url, source_link_catalog


LANGUAGES = ("ru", "en")
MAX_OUTPUT_TOKENS = 12000
SOURCE_DOCUMENT_MAX_CHARS = 100000
SOURCE_DOCUMENT_HEAD_CHARS = 4500
SOURCE_DOCUMENT_WINDOW_CHARS = 1050
SOURCE_DOCUMENT_MAX_BUCKETS = 512
SCHEMA_PATH = "contracts/schemas/new-summary.schema.json"
SKILL_PATH = "skills/new-summary/SKILL.md"
CHECKLIST_PATH = "contracts/new-summary-stage-checklists.json"

STAGE_LABELS = {
    "gate_1": "Gate 1",
    "gate_2": "Gate 2",
    "gate_3": "Gate 3",
    "stream_review_1": "Stream Review 1",
    "stream_review_2_plus": "Stream Review 2+",
    "progress_review": "Progress Review",
    "unknown": "Unknown",
}

INLINE_REQUIRED_DETAIL_TYPES = {
    "gate1_hypotheses_with_metrics": "hypotheses_with_thresholds",
    "gate2_hypothesis_results": "solution_validation",
    "gate2_user_flow": "source_links",
    "gate2_metric_linkage": "metric_binding",
    "gate2_commitments": "next_review_plan",
    "gate2_stop_criteria": "stop_criteria",
    "gate3_pmf_criteria": "criteria_list",
    "gate3_stop_criteria": "stop_criteria",
    "progress_review_stop_criteria": "stop_criteria",
    "progress_review_plan_fact_last_half_year": "plan_fact",
    "stream_review_2_plus_plan_fact_last_half_year": "plan_fact",
    "progress_review_next_half_year_plan": "next_review_plan",
    "stream_review_1_stop_criteria": "stop_criteria",
    "stream_review_1_solution_validation": "solution_validation",
    "stream_review_1_input_output_metric_link": "metric_binding",
    "stream_review_1_half_year_plan_with_metrics": "next_review_plan",
    "stream_review_2_plus_stop_criteria": "stop_criteria",
    "stream_review_2_plus_next_half_year_plan": "next_review_plan",
}
DETAIL_REPLACES_EVIDENCE = {
    "gate2_hypothesis_results",
    "gate2_metric_linkage",
    "gate2_commitments",
    "gate3_pmf_criteria",
    "progress_review_next_half_year_plan",
    "progress_review_plan_fact_last_half_year",
    "stream_review_2_plus_plan_fact_last_half_year",
    "stream_review_1_solution_validation",
    "stream_review_1_input_output_metric_link",
    "stream_review_1_half_year_plan_with_metrics",
    "stream_review_2_plus_next_half_year_plan",
}

def generate_and_persist_new_summary_report(
    *,
    session: Session,
    analysis: Analysis,
    check_run: AnalysisCheckRun,
    source_payload: dict[str, Any],
    provider: Provider,
    model: str,
    api_key: str | None,
    base_url: str | None,
) -> dict[str, Any]:
    revision = str(check_run.id)
    diagnostic_context = {
        "analysis_id": str(analysis.id),
        "check_run_id": str(check_run.id),
        "provider": provider.value,
        "model": model,
        "document_stage": source_payload.get("document_stage"),
        "document_type": source_payload.get("document_type"),
    }
    response_schema = _new_summary_schema()
    mark_new_summary_progress(analysis=analysis, revision=revision, stage="preparing_prompt")
    session.commit()
    anonymization = anonymize_value_for_model(
        source_payload,
        existing_metadata=(check_run.run_parameters or {}).get(RUN_PARAMETER_KEY)
        or (analysis.run_parameters or {}).get(RUN_PARAMETER_KEY),
    )
    anonymized_source_payload = provider_source_links(deepcopy(
        anonymization.value if isinstance(anonymization.value, dict) else source_payload
    ))
    prompt = _generation_prompt(
        source_payload=anonymized_source_payload,
        response_schema=response_schema,
    )
    _log_new_summary_phase(
        "preparing_prompt",
        {
            **diagnostic_context,
            "prompt_chars": len(prompt),
            "schema_path": SCHEMA_PATH,
            "skill_path": SKILL_PATH,
            "source_sections": sorted(source_payload.keys()),
            "source_link_count": len((source_payload.get("source_document") or {}).get("links") or []),
            "source_document_excerpt_chars": len(
                str(((source_payload.get("source_document") or {}).get("parsed_text_excerpt") or ""))
            )
            if isinstance(source_payload.get("source_document"), dict)
            else 0,
        },
    )
    run_parameters = dict(check_run.run_parameters or {})
    mock_result = run_parameters.get("new_summary_mock_provider_result")
    if isinstance(mock_result, dict):
        run_parameters["mock_provider_result"] = mock_result
    apply_ic_review_provider_defaults(run_parameters)
    run_parameters["max_output_tokens"] = MAX_OUTPUT_TOKENS
    run_parameters["max_retries"] = max(1, int(run_parameters.get("max_retries") or 0))
    if provider == Provider.OPENAI_COMPATIBLE:
        run_parameters["response_format"] = {"type": "json_object"}
    run_parameters["new_summary_language"] = "bilingual"
    run_parameters["new_summary_provider"] = provider.value
    run_parameters["new_summary_model"] = model
    run_parameters["new_summary_generation_mode"] = NEW_SUMMARY_GENERATION_MODE
    run_parameters[RUN_PARAMETER_KEY] = db_safe_anonymization_metadata(anonymization.metadata) or {"enabled": False}

    step = start_result_synthesis_step(
        session=session,
        check_run=check_run,
        step_name="new_summary_bilingual",
        prompt=prompt,
        run_parameters=run_parameters,
        skill=None,
        fallback_skill_metadata={
            "name": "new-summary",
            "version": str(NEW_SUMMARY_VERSION),
            "source_type": "repository_skill",
            "source_path": SKILL_PATH,
            "result_schema_path": SCHEMA_PATH,
        },
    )
    diagnostic_context["step_id"] = str(step.id)
    for language in LANGUAGES:
        mark_new_summary_running(analysis=analysis, revision=revision, language=language)
    mark_new_summary_progress(analysis=analysis, revision=revision, stage="generating")
    session.commit()

    provider_results: list[AnalysisProviderResult] = []
    try:
        _log_new_summary_phase("generating", diagnostic_context)
        payload = _run_generation_with_json_retry(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            prompt=prompt,
            response_schema=response_schema,
            source_payload=source_payload,
            anonymization_metadata=run_parameters.get(RUN_PARAMETER_KEY),
            run_parameters=run_parameters,
            attempt_results=provider_results,
            diagnostics_context=diagnostic_context,
        )
    except Exception as exc:
        session.rollback()
        public_error = public_new_summary_error_message(exc)
        diagnostics = _new_summary_error_diagnostics(
            exc,
            {
                **diagnostic_context,
                "phase": "generation_failed",
                "public_error": public_error,
                "attempt_count": len(provider_results),
                "attempts": _provider_attempt_diagnostics(provider_results),
                "prompt_chars": len(prompt),
                "schema_chars": len(json.dumps(response_schema, ensure_ascii=False)),
                "source_payload_chars": len(json.dumps(source_payload, ensure_ascii=False, default=str)),
            },
        )
        _log_new_summary_failure(
            exc,
            {
                **diagnostics,
            },
        )
        fail_result_synthesis_step(
            session=session,
            step=step,
            error_message=public_error,
            raw_output=_combined_raw_output(provider_results),
            diagnostics=diagnostics,
        )
        mark_new_summary_failed(
            analysis=analysis,
            revision=revision,
            language="ru",
            error_message=public_error,
        )
        mark_new_summary_failed(
            analysis=analysis,
            revision=revision,
            language="en",
            error_message=public_error,
        )
        session.commit()
        raise

    try:
        session.refresh(analysis)
        if _analysis_chain_cancel_requested(analysis):
            diagnostics = _new_summary_error_diagnostics(
                RuntimeError("cancelled_by_user"),
                {
                    **diagnostic_context,
                    "phase": "cancelled_after_generation",
                    "public_error": "cancelled_by_user",
                    "attempt_count": len(provider_results),
                    "attempts": _provider_attempt_diagnostics(provider_results),
                    "provider_raw_output_present": bool(_combined_raw_output(provider_results)),
                },
            )
            cancel_result_synthesis_step(
                session=session,
                step=step,
                error_message="cancelled_by_user",
                raw_output=_combined_raw_output(provider_results),
                diagnostics=diagnostics,
            )
            mark_new_summary_cancelled(analysis=analysis, revision=revision)
            session.commit()
            _log_new_summary_phase(
                "cancelled",
                {
                    **diagnostic_context,
                    "attempt_count": len(provider_results),
                    "attempts": _provider_attempt_diagnostics(provider_results),
                },
            )
            return {}
        mark_new_summary_progress(analysis=analysis, revision=revision, stage="saving")
        session.commit()
        variants = _split_bilingual_report(payload)
        source_fingerprint = new_summary_source_fingerprint(source_payload)
        for language in LANGUAGES:
            persist_new_summary_variant(
                analysis=analysis,
                revision=revision,
                language=language,
                payload=variants[language],
                source_fingerprint=source_fingerprint,
                trace_step_id=str(step.id),
            )
        _log_new_summary_phase(
            "completed",
            {
                **diagnostic_context,
                "attempt_count": len(provider_results),
                "attempts": _provider_attempt_diagnostics(provider_results),
                "ru_payload_keys": sorted(variants["ru"].keys()),
                "en_payload_keys": sorted(variants["en"].keys()),
            },
        )
        complete_result_synthesis_step(
            session=session,
            step=step,
            raw_output=_combined_raw_output(provider_results),
            structured_output=payload,
            input_tokens=_sum_optional(provider_results, "input_tokens"),
            output_tokens=_sum_optional(provider_results, "output_tokens"),
            latency_ms=_sum_optional(provider_results, "latency_ms"),
            estimated_cost=_sum_optional(provider_results, "estimated_cost"),
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        public_error = public_new_summary_error_message(exc)
        diagnostics = _new_summary_error_diagnostics(
            exc,
            {
                **diagnostic_context,
                "phase": "saving_failed",
                "public_error": public_error,
                "attempt_count": len(provider_results),
                "attempts": _provider_attempt_diagnostics(provider_results),
                "provider_raw_output_present": bool(_combined_raw_output(provider_results)),
                "payload_keys": sorted(payload.keys()),
            },
        )
        _log_new_summary_failure(exc, diagnostics)
        fail_result_synthesis_step(
            session=session,
            step=step,
            error_message=public_error,
            raw_output=_combined_raw_output(provider_results),
            diagnostics=diagnostics,
        )
        for language in LANGUAGES:
            mark_new_summary_failed(
                analysis=analysis,
                revision=revision,
                language=language,
                error_message=public_error,
            )
        session.commit()
        raise
    return payload


def _analysis_chain_cancel_requested(analysis: Analysis) -> bool:
    return bool((analysis.run_parameters or {}).get("analysis_chain_cancel_requested_at"))


def build_new_summary_source(
    *,
    session: Session,
    analysis: Analysis,
    check_run: AnalysisCheckRun,
) -> dict[str, Any]:
    document = session.get(Document, analysis.document_id)
    if document is None:
        raise ValueError("source_document_missing")
    document_type = _document_type(analysis=analysis, document=document)
    stage = STAGE_LABELS.get(document_type)
    if stage is None:
        raise ValueError(f"unsupported_new_summary_stage:{document_type}")
    stage = progress_review_display_stage(document.parsed_text, document_type, title=document.title) or stage
    return {
        "initiative_title": _initiative_title(analysis=analysis, document=document),
        "document_stage": stage,
        "document_type": document_type,
        "source_document": _source_document_payload(document),
        "source_traction_tables": source_traction_tables(document),
        "gate_challenger": _gate_challenger_source(analysis.structured_output),
        "gate_challenger_detail": _latest_detail_source(session=session, analysis=analysis),
        "ic_review": _ic_review_source(check_run.structured_output),
    }


def new_summary_source_fingerprint(source_payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "source_payload": source_payload,
                "skill": {
                    "path": SKILL_PATH,
                    "version": NEW_SUMMARY_VERSION,
                    "text": _skill_text(),
                },
                "schema": {
                    "path": SCHEMA_PATH,
                    "value": _new_summary_schema(),
                },
                "checklist": {
                    "path": CHECKLIST_PATH,
                    "value": _new_summary_stage_checklists(),
                },
            },
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _document_type(*, analysis: Analysis, document: Document) -> str:
    run_parameters = analysis.run_parameters or {}
    for value in (
        run_parameters.get("document_type_override"),
        run_parameters.get("document_type"),
        document.manual_document_type,
        document.detected_document_type,
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown"


def _initiative_title(*, analysis: Analysis, document: Document) -> str:
    output = analysis.structured_output if isinstance(analysis.structured_output, dict) else {}
    result = output.get("result") if isinstance(output.get("result"), dict) else {}
    for value in (
        result.get("initiative_title"),
        result.get("title"),
        result.get("project_name"),
        output.get("initiative_title"),
        output.get("title"),
        output.get("project_name"),
        _initiative_title_from_text(document.parsed_text),
        document.title,
        document.original_filename,
    ):
        if isinstance(value, str) and value.strip():
            title = clean_initiative_title(value)
            if title == "Untitled initiative" or re.fullmatch(r"(?:page|страница)\s+\d+(?:\s+(?:of|из)\s+\d+)?", title, flags=re.IGNORECASE):
                continue
            filename = document.original_filename or ""
            if filename[:len(title)].casefold() == title.casefold():
                return filename[:len(title)]
            return title
    return "Untitled initiative"


def _initiative_title_from_text(text: str | None) -> str | None:
    if not isinstance(text, str):
        return None
    lines = [_clean_title_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    for line in lines[:80]:
        lowered = line.lower()
        for marker in (
            "название инициативы",
            "название проекта",
            "инициатива",
            "проект",
            "initiative name",
            "project name",
        ):
            if lowered.startswith(marker):
                value = line.split(":", 1)[1].strip() if ":" in line else ""
                if _is_plausible_initiative_title(value):
                    return value
    for line in lines[:20]:
        if _is_plausible_initiative_title(line):
            return line
    return None


def _clean_title_line(line: str) -> str:
    return line.strip().strip("#").strip(" -*\t")


def _is_plausible_initiative_title(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    title = value.strip()
    if len(title) < 4 or len(title) > 160:
        return False
    if re.fullmatch(r"\[?(?:page|страница)\s+\d+(?:\s+(?:of|из)\s+\d+)?\]?", title, flags=re.IGNORECASE):
        return False
    if re.fullmatch(r"\[image on page \d+:[^\]]+\]", title, flags=re.IGNORECASE):
        return False
    lowered = title.lower()
    if lowered in {"gate 1", "gate 2", "gate 3", "stream review", "progress review"}:
        return False
    if lowered.endswith((".docx", ".pdf", ".xlsx", ".pptx")):
        return False
    return any(character.isalpha() for character in title)


def _gate_challenger_source(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = value.get("result") if isinstance(value.get("result"), dict) else {}
    return {
        "verdict": _copy_jsonish(result.get("verdict") or value.get("verdict")),
        "short_summary": _copy_jsonish(result.get("short_summary") or value.get("summary")),
        "stage_checklist": _copy_jsonish(value.get("stage_checklist") or result.get("stage_checklist")),
        "findings": _copy_jsonish(result.get("findings") or value.get("findings")),
        "checks": _copy_jsonish(result.get("checks") or value.get("checks")),
        "layer_1": _copy_jsonish(result.get("layer_1") or value.get("layer_1")),
        "layer_2": _copy_jsonish(result.get("layer_2") or value.get("layer_2")),
        "layer_1_index": _copy_jsonish(result.get("layer_1_index") or value.get("layer_1_index")),
        "layer_2_index": _copy_jsonish(result.get("layer_2_index") or value.get("layer_2_index")),
        "critical_risks": _copy_jsonish(result.get("critical_risks")),
        "data_gaps": _copy_jsonish(result.get("data_gaps")),
        "rationale_items": _copy_jsonish(result.get("rationale_items")),
        "rationale_markdown": _copy_jsonish(result.get("rationale_markdown")),
        "assessment_markdown": _copy_jsonish(
            value.get("assessment_markdown")
            or value.get("native_markdown")
            or value.get("markdown")
            or value.get("output_markdown")
            or value.get("summary_markdown")
        ),
    }


def _ic_review_source(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = (
        "verdict",
        "executive_brief",
        "confidence",
        "top_findings",
        "key_numbers",
        "spreadsheet_audit",
        "critical_risks",
        "data_gaps",
        "required_actions",
        "validation",
    )
    return {key: _copy_jsonish(value.get(key)) for key in keys if key in value}


def _source_document_payload(document: Document) -> dict[str, Any]:
    parsed_text = document.parsed_text.strip() if isinstance(document.parsed_text, str) else ""
    extra_links = []
    link_extraction = "parsed_text"
    if str(document.original_filename or "").lower().endswith(".pdf") and document.storage_path:
        try:
            raw_path = LocalDocumentStorage(get_settings().storage_root).stored_path(document.storage_path)
            extra_links = pdf_source_links(raw_path)
            link_extraction = "parsed_text_and_pdf_annotations"
        except Exception as exc:
            # Optional link recovery must not fail a completed financial/product review.
            link_extraction = "pdf_annotations_unavailable"
            worker_logger.warning("new_summary_source_links_unavailable", extra={
                "document_id": str(document.id), "error_class": type(exc).__name__,
            })
    return {
        "title": document.title,
        "original_filename": document.original_filename,
        "detected_document_type": document.detected_document_type,
        "manual_document_type": document.manual_document_type,
        "parsed_text_excerpt": _bounded_source_text(parsed_text),
        "links": source_link_catalog(parsed_text, extra_links=extra_links),
        "link_extraction": link_extraction,
    }


def _bounded_source_text(value: str) -> str:
    if len(value) <= SOURCE_DOCUMENT_MAX_CHARS:
        return value

    head_end = _source_line_end(value, SOURCE_DOCUMENT_HEAD_CHARS)
    head = value[:head_end].rstrip()
    candidates: list[tuple[int, int, int]] = []
    bucket_size = max(
        SOURCE_DOCUMENT_WINDOW_CHARS,
        (len(value) - head_end + SOURCE_DOCUMENT_MAX_BUCKETS - 1) // SOURCE_DOCUMENT_MAX_BUCKETS,
    )
    for bucket_start in range(head_end, len(value), bucket_size):
        bucket_end = min(len(value), bucket_start + bucket_size)
        best_defense: tuple[int, int, int] | None = None
        best_context: tuple[int, int, int] | None = None
        best_scope: tuple[int, int, int] | None = None
        for scan_start in range(bucket_start, bucket_end, SOURCE_DOCUMENT_WINDOW_CHARS):
            scan = value[scan_start:min(bucket_end, scan_start + SOURCE_DOCUMENT_WINDOW_CHARS)]
            defense_match = CURRENT_DEFENSE_MARKERS.search(scan)
            scope_match = CURRENT_SCOPE_MARKERS.search(scan)
            context_match = (
                SELECTED_SCENARIO_MARKERS.search(scan)
                or CURRENT_DECISION_MARKERS.search(scan)
                or CONTEXT_CANDIDATE_MARKERS.search(scan)
            )
            for match, kind in ((defense_match, "defense"), (context_match, "context"), (scope_match, "scope")):
                if match is None:
                    continue
                match_start = scan_start + match.start()
                match_end = scan_start + match.end()
                start = max(head_end, match_start - 250)
                line_start = value.rfind("\n", start, match_start)
                if line_start >= start:
                    start = line_start + 1
                end = min(len(value), start + SOURCE_DOCUMENT_WINDOW_CHARS)
                line_end = value.rfind("\n", match_end, end)
                if line_end > match_end:
                    end = line_end
                candidate = (decision_context_score(value[start:end]), start, end)
                if kind == "defense":
                    best_defense = max(best_defense, candidate) if best_defense else candidate
                elif kind == "context":
                    best_context = max(best_context, candidate) if best_context else candidate
                else:
                    best_scope = max(best_scope, candidate) if best_scope else candidate
        for candidate in (best_defense, best_context, best_scope):
            if candidate is not None and candidate not in candidates:
                candidates.append(candidate)

    selected: list[tuple[int, int]] = []
    remaining = SOURCE_DOCUMENT_MAX_CHARS - len(head) - 120
    defense_candidates = [
        candidate for candidate in candidates
        if CURRENT_DEFENSE_MARKERS.search(value[candidate[1]:candidate[2]])
    ]
    if defense_candidates:
        _score, start, end = max(defense_candidates, key=lambda item: (item[0], item[1]))
        defense_cost = len(value[start:end].strip()) + 55
        if defense_cost <= remaining:
            selected.append((start, end))
            remaining -= defense_cost
    scope_candidates = sorted(
        (candidate for candidate in candidates if CURRENT_SCOPE_MARKERS.search(value[candidate[1]:candidate[2]])),
        key=lambda item: (item[0], item[1]),
        reverse=True,
    )
    for _score, start, end in scope_candidates:
        if any(start < prior_end and end > prior_start for prior_start, prior_end in selected):
            continue
        scope_cost = len(value[start:end].strip()) + 55
        if scope_cost <= remaining:
            selected.append((start, end))
            remaining -= scope_cost
            break
    for _score, start, end in sorted(candidates, key=lambda item: (-item[0], item[1])):
        if any(start < prior_end and end > prior_start for prior_start, prior_end in selected):
            continue
        fragment = value[start:end].strip()
        cost = len(fragment) + 55
        if cost > remaining:
            continue
        selected.append((start, end))
        remaining -= cost

    if not selected:
        suffix = "\n\n[TRUNCATED: remaining source text was omitted.]"
        excerpt = value[: SOURCE_DOCUMENT_MAX_CHARS - len(suffix)]
        boundary = excerpt.rfind("\n")
        if boundary > SOURCE_DOCUMENT_MAX_CHARS // 2:
            excerpt = excerpt[:boundary]
        return excerpt.rstrip() + suffix

    ordered = sorted(selected)
    fillers: list[tuple[int, int]] = []
    cursor = head_end
    for start, end in [*ordered, (len(value), len(value))]:
        if cursor < start and remaining > 55:
            fill_end = min(start, cursor + remaining - 55)
            fragment = value[cursor:fill_end].strip()
            if fragment:
                fillers.append((cursor, fill_end))
                remaining -= len(fragment) + 55
        cursor = max(cursor, end)

    parts = [head, "[SOURCE EXCERPTS FROM THE DOCUMENT; OTHER TEXT OMITTED]"]
    for start, end in sorted([*selected, *fillers]):
        parts.append(f"[Source chars {start}-{end}]\n{value[start:end].strip()}")
    return "\n\n".join(parts)


def _source_line_end(value: str, limit: int) -> int:
    boundary = value.rfind("\n", 0, limit)
    return boundary + 1 if boundary > limit // 2 else limit


def _copy_jsonish(value: Any) -> Any:
    return deepcopy(value)


def _generation_prompt(
    *,
    source_payload: dict[str, Any],
    response_schema: dict[str, Any],
) -> str:
    return "\n\n".join(
        [
            _skill_text().strip(),
            "## Runtime instruction",
            "Собери ровно один bilingual JSON-объект по схеме ниже.",
            "Первая версия в `versions[]` должна быть английской, вторая — русской.",
            "`document_stage` — текущая стадия инициативы для заголовка и контекста; `document_type` задаёт только набор правил проверки. Если они отличаются, не называй текущую стадию по `document_type`.",
            "Фрагменты `source_document.parsed_text_excerpt` взяты из разных частей исходного документа и не являются полным текстом. Отличай явно выбранный текущий сценарий и фокус инициативы от старых, расчётных и альтернативных вариантов; при неразрешённом противоречии не угадывай, какой вариант действует.",
            "В фоновом запуске нет MCP или браузера: не утверждай, что открыл внешнюю ссылку. Оценивай её содержимое только если оно уже присутствует во входных результатах.",
            "Для Mockups, видео, дизайна или пользовательского flow выбирай подходящие ссылки из source_document.links по label/context, включая FAQ 1 и подписи See full design here или MLP. Верни source_link_id, точно равный id выбранной ссылки, вместо url. Адреса скрыты анонимизатором: это НЕ означает, что ссылки невозможно скопировать; сервер восстановит их по id. Не выбирай финансовые модели, исследования и другие ссылки только потому, что они рядом. Наличие ссылки не доказывает содержимое файла по ней.",
            "Для статуса пункта Mockups достаточно хотя бы одной такой исходной ссылки: поставь Есть, не проверяя содержимое по адресу.",
            "Для Traction Summary верни одну таблицу: `traction_summary` с годовыми `periods` и четырьмя строками `rows` в порядке схемы. При конфликте исходных таблиц для Total Revenue выбирай всю строку Financial Model текущего сценария, а не отдельно итоговую ячейку. Не бери годовые значения из одной таблицы, а Total из другой. Если Total той же строки и показанного периода нет, вычисляй его только из полного ряда её годовых чисел; сервер дополнительно проверит источник и пересчитает неподтверждённый Total. Поле `total_revenue_provenance` заполняет сервер, не выдумывай его. Даже при отсутствии чисел оставь эти строки и `Total`, поставь прочерки; не выдумывай периоды и значения.",
            "Не добавляй Markdown вокруг JSON. Не добавляй пояснения вне JSON.",
            "## JSON Schema",
            json.dumps(response_schema, ensure_ascii=False, indent=2),
            "## Input data",
            json.dumps(source_payload, ensure_ascii=False, indent=2, default=str),
        ]
    )


def _run_generation_with_json_retry(
    *,
    provider: Provider,
    model: str,
    api_key: str | None,
    base_url: str | None,
    prompt: str,
    response_schema: dict[str, Any],
    source_payload: dict[str, Any],
    anonymization_metadata: dict[str, Any] | None,
    run_parameters: dict[str, Any],
    attempt_results: list[AnalysisProviderResult],
    diagnostics_context: dict[str, Any],
) -> dict[str, Any]:
    result = _call_provider(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        prompt=prompt,
        response_schema=response_schema,
        run_parameters={**run_parameters, "new_summary_json_retry": False},
    )
    attempt_results.append(result)
    try:
        _log_new_summary_phase(
            "validating",
            {
                **diagnostics_context,
                "attempt": 1,
                "attempts": _provider_attempt_diagnostics(attempt_results),
            },
        )
        return _validated_new_summary(
            result,
            response_schema,
            source_payload=source_payload,
            anonymization_metadata=anonymization_metadata,
        )
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        _log_new_summary_failure(
            exc,
            {
                **diagnostics_context,
                "phase": "first_attempt_invalid",
                "public_error": public_new_summary_error_message(exc),
                "attempt": 1,
                "attempts": _provider_attempt_diagnostics(attempt_results),
            },
        )
        retry_parameters = {**run_parameters, "new_summary_json_retry": True}
        retry_mock = run_parameters.get("new_summary_json_retry_mock_provider_result")
        if isinstance(retry_mock, dict):
            retry_parameters["mock_provider_result"] = retry_mock
        retry_result = _call_provider(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            prompt=(
                prompt.rstrip()
                + "\n\nJSON RETRY: previous response was invalid or incomplete "
                + f"({exc.__class__.__name__}). Return exactly one complete JSON object that matches the schema."
            ),
            response_schema=response_schema,
            run_parameters=retry_parameters,
        )
        attempt_results.append(retry_result)
        _log_new_summary_phase(
            "validating",
            {
                **diagnostics_context,
                "attempt": 2,
                "attempts": _provider_attempt_diagnostics(attempt_results),
            },
        )
        return _validated_new_summary(
            retry_result,
            response_schema,
            source_payload=source_payload,
            anonymization_metadata=anonymization_metadata,
        )


def _call_provider(
    *,
    provider: Provider,
    model: str,
    api_key: str | None,
    base_url: str | None,
    prompt: str,
    response_schema: dict[str, Any],
    run_parameters: dict[str, Any],
) -> AnalysisProviderResult:
    provider_parameters = provider_safe_run_parameters(run_parameters)
    return get_provider_adapter(provider, provider_parameters).run(
        ProviderRunRequest(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            prompt=prompt,
            response_schema=response_schema,
            run_parameters=provider_parameters,
        )
    )


def _validated_new_summary(
    result: AnalysisProviderResult,
    response_schema: dict[str, Any],
    *,
    source_payload: dict[str, Any],
    anonymization_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = parse_json_output(result.structured_text)
    payload = deanonymize_model_value(payload, metadata=anonymization_metadata)
    return _validated_source_dependent_report(
        payload=payload,
        source_payload=source_payload,
        response_schema=response_schema,
    )


def _validated_source_dependent_report(
    *,
    payload: dict[str, Any],
    source_payload: dict[str, Any],
    response_schema: dict[str, Any],
) -> dict[str, Any]:
    payload = _normalize_generated_report_shell(payload=payload, source_payload=source_payload)
    if not isinstance(payload, dict):
        raise ValueError("new_summary_not_object")
    if payload.get("language") != "en":
        raise ValueError("new_summary_language_mismatch")
    expected_stage = source_payload.get("document_stage")
    normalized = dict(payload)
    versions = normalized.get("versions")
    if not isinstance(versions, list) or len(versions) != 2:
        raise ValueError("new_summary_versions_mismatch")
    normalized_versions: list[dict[str, Any]] = []
    for expected_language, version in zip(("en", "ru"), versions, strict=True):
        if not isinstance(version, dict) or version.get("language") != expected_language:
            raise ValueError("new_summary_version_language_mismatch")
        if isinstance(expected_stage, str) and version.get("stage") != expected_stage:
            raise ValueError("new_summary_stage_mismatch")
        normalized_version = dict(version)
        normalized_version["required_details"] = _normalized_required_details(version)
        normalized_version["required_elements"] = _required_elements_from_source(
            source_payload=source_payload,
            target_language=expected_language,
            generated_payload=version,
            required_details=normalized_version["required_details"],
        )
        for element in normalized_version["required_elements"]:
            if "detail" in element:
                normalized_version["required_details"].pop(element["id"], None)
        # Historical reports are read from storage unchanged; new reports never create appendices.
        normalized_version.pop("required_details", None)
        source_tables = source_payload.get("source_traction_tables")
        # The legacy extractor selects only two broad rows; replacing the four
        # new metric rows with it would erase DTB-sourced and non-DTB revenue.
        normalized_version = with_traction_totals(
            {**normalized_version, "schema_version": normalized["schema_version"]},
            source_tables=source_tables if isinstance(source_tables, list) and source_tables else None,
            strict_total_source=True,
        )
        normalized_version.pop("schema_version", None)
        if isinstance(expected_stage, str):
            normalized_version = with_summary_display_stage(normalized_version, expected_stage)
        normalized_versions.append(normalized_version)
    normalized["versions"] = normalized_versions
    validate(instance=normalized, schema=response_schema)
    return normalized


def _normalize_generated_report_shell(*, payload: dict[str, Any], source_payload: dict[str, Any]) -> dict[str, Any]:
    """Repair technical JSON drift while preserving model-authored content."""
    if not isinstance(payload, dict):
        return payload

    normalized = _filter_allowed_keys(
        payload,
        allowed={"schema_version", "language", "title", "versions"},
    )
    normalized["schema_version"] = "new-summary-v8"
    normalized.setdefault("language", "en")
    normalized["title"] = display_new_summary_title(_source_initiative_title(source_payload))

    versions = normalized.get("versions")
    if not isinstance(versions, list):
        versions = []
    ordered_versions = _ordered_versions_with_inferred_languages(versions)
    normalized["versions"] = [
        _normalize_generated_version_shell(
            version,
            source_payload=source_payload,
            language=language,
        )
        for language, version in zip(("en", "ru"), ordered_versions, strict=True)
    ]
    return normalized


def _ordered_versions_with_inferred_languages(versions: list[Any]) -> list[dict[str, Any]]:
    dict_versions = [version for version in versions if isinstance(version, dict)]
    by_language: dict[str, dict[str, Any]] = {}
    unlabeled: list[dict[str, Any]] = []
    for version in dict_versions:
        language = version.get("language")
        if language in LANGUAGES and language not in by_language:
            by_language[language] = version
        else:
            unlabeled.append(version)
    for language in ("en", "ru"):
        if language not in by_language and unlabeled:
            by_language[language] = unlabeled.pop(0)
    return [by_language.get("en") or {}, by_language.get("ru") or {}]


def _normalize_generated_version_shell(
    version: dict[str, Any],
    *,
    source_payload: dict[str, Any],
    language: str,
) -> dict[str, Any]:
    normalized = _filter_allowed_keys(
        version,
        allowed={
            "language",
            "stage",
            "traction_summary",
            "context",
            "required_elements",
            "required_details",
            "critical_problems",
        },
    )
    normalized["language"] = language
    normalized["stage"] = source_payload.get("document_stage") or normalized.get("stage")
    if not isinstance(normalized.get("context"), str) or not str(normalized.get("context")).strip():
        normalized["context"] = _missing_text(language, "context")
    normalized["traction_summary"] = _normalize_traction_summary(
        normalized.get("traction_summary"),
        language=language,
    )
    for key in ("required_elements", "critical_problems"):
        if not isinstance(normalized.get(key), list):
            normalized[key] = []
    for problem in normalized["critical_problems"]:
        if not isinstance(problem, dict) or not isinstance(problem.get("issue"), str):
            continue
        issue = problem["issue"].strip()
        if issue.startswith("**") and issue.endswith("**") and len(issue) > 4:
            problem["issue"] = issue[2:-2].strip()
    return normalized


def _filter_allowed_keys(value: dict[str, Any], *, allowed: set[str]) -> dict[str, Any]:
    return {key: _copy_jsonish(item) for key, item in value.items() if key in allowed}


def _source_initiative_title(source_payload: dict[str, Any]) -> str:
    title = source_payload.get("initiative_title")
    if isinstance(title, str) and title.strip():
        return clean_initiative_title(title)
    return "Untitled initiative"


def _normalize_traction_summary(value: Any, *, language: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    if "tables" in value:
        raise ValueError("new_summary_traction_format_mismatch")
    raw_periods = value.get("periods")
    raw_periods = [str(period).strip() for period in raw_periods] if isinstance(raw_periods, list) else []
    selected: dict[int, tuple[int, bool]] = {}
    total_index: int | None = None
    for index, period in enumerate(raw_periods):
        if re.search(r"\b(?:total|итого|всего)\b", period, re.IGNORECASE):
            total_index = index
            continue
        key = _period_key(period)
        if key is None or key[1:] not in {(1, 12), (7, 12)}:
            continue
        is_h2 = key[1:] == (7, 12)
        if key[0] not in selected or (selected[key[0]][1] and not is_h2):
            selected[key[0]] = (index, is_h2)
    annual_columns = [(year, *selected[year]) for year in sorted(selected)]
    periods = [str(year) for year, _, _ in annual_columns] + ["Total"]
    raw_rows = value.get("rows") if isinstance(value.get("rows"), list) else []
    labels = ("DTB Uplift (Cumul)", "Revenue from DTB", "Revenue non-DTB", "Total Revenue")
    if raw_rows and (len(raw_rows) != len(labels) or {row.get("label") for row in raw_rows if isinstance(row, dict)} != set(labels)):
        raise ValueError("new_summary_traction_rows_mismatch")
    by_label = {row.get("label"): row for row in raw_rows if isinstance(row, dict) and isinstance(row.get("label"), str)}
    rows = []
    for label in labels:
        source = by_label.get(label) or {}
        raw_values = source.get("values") if isinstance(source.get("values"), list) else []
        values = []
        for year, index, is_h2 in annual_columns:
            cell = _traction_cell(raw_values[index]) if index < len(raw_values) else "—"
            if is_h2:
                cell = f"{cell} (H2 {year})" if label == labels[0] and cell != "—" else "—"
            values.append(cell)
        values.append(_traction_cell(raw_values[total_index]) if total_index is not None and total_index < len(raw_values) else "—")
        if label == labels[0]:
            values[-1] = "—"
        row = {"label": label, "values": values}
        if label == labels[-1]:
            mismatches = source.get("mismatch_periods")
            if isinstance(mismatches, list):
                normalized_mismatches: set[str] = set()
                for period in mismatches:
                    key = _period_key(period)
                    if key and key[1:] == (1, 12):
                        normalized_mismatches.add(str(key[0]))
                    elif re.search(r"\b(?:total|итого|всего)\b", str(period), re.IGNORECASE):
                        normalized_mismatches.add("Total")
                row["mismatch_periods"] = [period for period in periods if period in normalized_mismatches]
        rows.append(row)
    return {"periods": periods, "rows": rows}


def _traction_cell(value: Any) -> str:
    text = str(value).strip() if value is not None else ""
    if not text or text in {"-", "–", "—"} or text.casefold() in {
        "значение не найдено в документе",
        "отсутствуют данные в документе защиты",
        "невозможно извлечь данные",
        "нет данных в документе",
        "не смог получить данные",
        "no data in the defense document",
        "could not extract data",
        "no data in the document",
        "value not found in the document",
    }:
        return "—"
    return text


def _missing_text(language: str, field: str) -> str:
    if language == "ru":
        return f"Данные для раздела `{field}` не были надежно выделены из входных анализов."
    return f"Data for `{field}` was not reliably extracted from the source analyses."


def _split_bilingual_report(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    title = str(payload.get("title") or "").strip()
    variants: dict[str, dict[str, Any]] = {}
    for version in payload.get("versions") or []:
        if not isinstance(version, dict):
            continue
        language = version.get("language")
        if language not in LANGUAGES:
            continue
        variants[language] = {
            "schema_version": payload["schema_version"],
            "title": title,
            **deepcopy(version),
        }
    if set(variants) != set(LANGUAGES):
        raise ValueError("new_summary_split_failed")
    return variants


def _required_elements_from_source(
    *,
    source_payload: dict[str, Any],
    target_language: str,
    generated_payload: dict[str, Any],
    required_details: dict[str, Any],
) -> list[dict[str, Any]]:
    document_type = source_payload.get("document_type")
    expected = _new_summary_stage_checklist_items(
        str(document_type) if isinstance(document_type, str) else None,
        output_language=target_language,
    )
    by_id = _gate_stage_checklist_by_id(source_payload)
    generated_by_id = _generated_required_elements_by_id(generated_payload)
    elements: list[dict[str, Any]] = []
    for item_id, label in expected:
        generated_item = generated_by_id.get(item_id)
        detail = _normalized_required_detail((generated_item or {}).get("detail"))
        if detail is None:
            detail = required_details.get(item_id)
        if not isinstance(detail, dict) or detail.get("type") != INLINE_REQUIRED_DETAIL_TYPES.get(item_id):
            detail = None
        if item_id == "gate2_user_flow":
            detail = _verified_source_links(detail, source_payload)
        if item_id.endswith("_stop_criteria") and detail is not None:
            primary = detail.get("primary_criterion", "")
            evidence_text = str((generated_item or {}).get("evidence") or "")
            detail["criteria"] = [criterion for criterion in detail["criteria"]
                                  if _text_key(criterion) not in {_text_key(primary), _text_key(evidence_text)}]
        element: dict[str, Any] = {
            "id": item_id,
            "label": label,
            "status": _required_element_status(
                by_id.get(item_id),
                item_id=item_id,
                generated_item=generated_item,
                required_details={**required_details, item_id: detail} if detail is not None else required_details,
            ),
        }
        evidence = _required_element_evidence(
            by_id.get(item_id),
            generated_item,
            target_language=target_language,
        )
        if item_id.endswith("_stop_criteria"):
            if evidence:
                evidence = _stop_terminology(evidence, target_language)
            if detail is not None:
                detail["criteria"] = [_stop_terminology(value, target_language) for value in detail["criteria"]]
                if detail.get("primary_criterion"):
                    detail["primary_criterion"] = _stop_terminology(detail["primary_criterion"], target_language)
                    evidence = evidence or detail["primary_criterion"]
        if item_id in {"gate2_hypothesis_results", "stream_review_1_solution_validation"} and detail is None:
            hypothesis = item_id == "gate2_hypothesis_results"
            evidence = (
                ("В кейсе не найдена информация о проверенных гипотезах" if hypothesis else
                 "В кейсе не найдена информация о подтверждении решения через количественники, прототипы или фейкдоры")
                if target_language == "ru" else
                ("No information about tested hypotheses was found in the case" if hypothesis else
                 "No information about solution validation through quantitative research, prototypes or fake doors was found in the case")
            )
        if evidence and not (detail is not None and item_id in DETAIL_REPLACES_EVIDENCE):
            element["evidence"] = evidence
        if detail is not None:
            element["detail"] = detail
        elements.append(element)
    if document_type == "stream_review_1":
        by_element_id = {element["id"]: element for element in elements}
        problem = by_element_id.get("stream_review_1_confirmed_problem")
        solution = by_element_id.get("stream_review_1_solution_validation")
        if problem and solution and problem["status"] == "есть":
            confirmed, separator, total = solution["status"].partition("/")
            if solution["status"] == "частично подтверждено" or (
                separator and confirmed.isdecimal() and total.isdecimal() and int(confirmed) < int(total)
            ):
                problem["status"] = "частично подтверждено"
    return elements


def _normalized_required_details(payload: dict[str, Any]) -> dict[str, Any]:
    details = payload.get("required_details")
    if not isinstance(details, dict):
        return {}
    normalized: dict[str, Any] = {}
    for item_id, detail in details.items():
        if not isinstance(item_id, str):
            continue
        normalized_detail = _normalized_required_detail(detail)
        if normalized_detail is not None:
            normalized[item_id] = normalized_detail
            normalized[_canonical_required_element_id(item_id)] = normalized_detail
    return normalized


def _normalized_required_detail(detail: Any) -> dict[str, Any] | None:
    if not isinstance(detail, dict):
        return None
    detail_type = detail.get("type")
    if detail_type == "hypotheses_with_thresholds":
        detail_items = detail.get("items")
        if not isinstance(detail_items, list):
            return None
        items = [
            {"hypothesis": hypothesis, "confirmation_condition": condition}
            for item in detail_items
            if isinstance(item, dict)
            for hypothesis in [_non_empty_string(item.get("hypothesis"))]
            for condition in [_non_empty_string(item.get("confirmation_condition"))]
            if hypothesis is not None and condition is not None
        ]
        return {"type": detail_type, "items": items} if items else None
    if detail_type == "solution_validation":
        detail_items = detail.get("items")
        if not isinstance(detail_items, list):
            return None
        items = []
        for item in detail_items:
            if not isinstance(item, dict):
                continue
            text = _non_empty_string(item.get("text"))
            verdict = _enum_value(item.get("verdict"), {"confirmed", "insufficient"})
            if text is None or verdict is None:
                continue
            for suffix in (
                " (Confirmed)", " (Not sufficiently confirmed)",
                " (Подтверждено)", " (Недостаточно подтверждено)",
            ):
                if text.casefold().endswith(suffix.casefold()):
                    text = text[:-len(suffix)].rstrip()
                    break
            if not text:
                continue
            if any(entry["text"].casefold() == text.casefold() for entry in items):
                continue
            normalized_item = {"text": text, "verdict": verdict}
            items.append(normalized_item)
        items.sort(key=lambda item: item["verdict"] != "confirmed")
        return {"type": detail_type, "items": items} if items else None
    if detail_type == "metric_binding":
        seen: set[str] = set()
        return {
            "type": detail_type,
            "input_metrics": _normalized_metric_binding_items(detail.get("input_metrics"), seen=seen),
            "output_metrics": _normalized_metric_binding_items(detail.get("output_metrics"), seen=seen),
        }
    if detail_type == "next_review_plan":
        outputs = _non_empty_strings(detail.get("outputs_until_next_review"))
        metrics = _normalized_metric_plan_rows(detail.get("metrics_until_next_review"))
        if not outputs and not metrics:
            return None
        return {
            "type": detail_type,
            "outputs_until_next_review": outputs,
            "metrics_until_next_review": metrics,
        }
    if detail_type == "stop_criteria":
        criteria = list({_text_key(value): value for value in _non_empty_strings(detail.get("criteria"))}.values())
        primary = _non_empty_string(detail.get("primary_criterion"))
        return {"type": detail_type, "criteria": criteria, **({"primary_criterion": primary} if primary else {})}
    if detail_type == "plan_fact":
        launches = [
            {"output": output, "status": status, **({"comment": comment} if comment else {})}
            for item in detail.get("launches", []) if isinstance(item, dict)
            for output in [_non_empty_string(item.get("output"))]
            for status in [_enum_value(item.get("status"), {"completed", "partial", "not_completed", "unknown"})]
            for comment in [_non_empty_string(item.get("comment"))]
            if output and status
        ] if isinstance(detail.get("launches"), list) else []
        metrics = [
            {"metric": metric, "planned": item["planned"], "actual": item["actual"]}
            for item in detail.get("metrics", []) if isinstance(item, dict)
            for metric in [_non_empty_string(item.get("metric"))]
            if metric and isinstance(item.get("planned"), str) and isinstance(item.get("actual"), str)
        ] if isinstance(detail.get("metrics"), list) else []
        return {"type": detail_type, "launches": launches, "metrics": metrics}
    if detail_type == "source_links":
        links = [
            {"label": label, **({"source_link_id": link_id} if link_id else {"url": url})}
            for item in detail.get("links", []) if isinstance(item, dict)
            for label in [_non_empty_string(item.get("label"))]
            for url in [_non_empty_string(item.get("url"))]
            for link_id in [_non_empty_string(item.get("source_link_id"))]
            if label and (link_id or safe_source_url(url))
        ] if isinstance(detail.get("links"), list) else []
        availability = _enum_value(detail.get("availability"), {"provided", "absent", "unavailable"})
        return {"type": detail_type, "availability": availability or "unavailable", "links": links}
    if detail_type == "criteria_list":
        criteria = _non_empty_strings(detail.get("criteria"))
        return {"type": detail_type, "criteria": criteria} if criteria else None
    return None


def _verified_source_links(detail: dict[str, Any] | None, source: dict[str, Any]) -> dict[str, Any]:
    document = source.get("source_document")
    text = str(document.get("parsed_text_excerpt") or "") if isinstance(document, dict) else ""
    catalog = document.get("links", []) if isinstance(document, dict) else []
    catalog = [item for item in catalog if isinstance(item, dict) and safe_source_url(item.get("url"))]
    by_id = {item.get("id"): item for item in catalog if item.get("id")}
    source_urls = {item["url"] for item in source_link_catalog(text)} | {item["url"] for item in catalog}
    detail = detail or {"availability": "unavailable", "links": []}
    links = []
    for item in detail.get("links", []):
        selected = by_id.get(item.get("source_link_id"))
        url = selected["url"] if selected else item.get("url")
        if item.get("source_link_id") and selected is None:
            continue
        if url in source_urls and safe_source_url(url) and not any(link["url"] == url for link in links):
            links.append({"label": item["label"], "url": url})
    availability = "provided" if links else (
        "absent" if detail.get("availability") == "absent" and not detail.get("links") and text
        and (not isinstance(document, dict) or document.get("link_extraction") != "pdf_annotations_unavailable") else "unavailable"
    )
    return {"type": "source_links", "availability": availability, "links": links}


def _normalized_metric_binding_items(value: Any, *, seen: set[str] | None = None) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    items = [
        {"metric": metric, "binding": binding, "evidence": evidence}
        for item in value
        if isinstance(item, dict)
        for metric in [_non_empty_string(item.get("metric"))]
        for binding in [_enum_value(item.get("binding"), {"confirmed", "insufficient"})]
        for evidence in [_non_empty_string(item.get("evidence"))]
        if metric is not None and binding is not None and evidence is not None
    ]
    seen = seen if seen is not None else set()
    unique = []
    for item in items:
        key = _text_key(item["metric"])
        if key not in seen:
            unique.append(item)
            seen.add(key)
    unique.sort(key=lambda item: item["binding"] != "confirmed")
    return unique


def _text_key(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def _stop_terminology(value: str, language: str) -> str:
    return re.sub(r"\b(?:stop[\s_\-–—]*loss(?:es)?|стоп[\s_\-–—]*лосс?\w*)\b",
                  "stop criteria" if language == "en" else "stop-критерии", value, flags=re.IGNORECASE)


def _normalized_metric_plan_rows(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {"metric": metric, "current": current, "next_review": next_review}
        for item in value
        if isinstance(item, dict)
        for metric in [_non_empty_string(item.get("metric"))]
        for current in [item.get("current")]
        for next_review in [item.get("next_review")]
        if metric is not None and isinstance(current, str) and isinstance(next_review, str)
    ]


def _non_empty_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (_non_empty_string(raw) for raw in value) if item is not None]


def _non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _enum_value(value: Any, allowed: set[str]) -> str | None:
    if not isinstance(value, str):
        return None
    return value if value in allowed else None


def _latest_detail_source(*, session: Session, analysis: Analysis) -> Any:
    detail_run = session.execute(
        select(AnalysisDetailRun)
        .where(
            AnalysisDetailRun.analysis_id == analysis.id,
            AnalysisDetailRun.status == RunStatus.COMPLETED.value,
        )
        .order_by(AnalysisDetailRun.created_at.desc())
    ).scalars().first()
    return _copy_jsonish(detail_run.structured_output) if detail_run and isinstance(detail_run.structured_output, dict) else None


def _new_summary_stage_checklist_items(document_type: str | None, *, output_language: str) -> list[tuple[str, str]]:
    language_key = "label_en" if output_language == "en" else "label_ru"
    return [
        (item["id"], item[language_key])
        for item in _new_summary_stage_checklists().get(str(document_type or ""), [])
    ]


@lru_cache(maxsize=1)
def _new_summary_stage_checklists() -> dict[str, list[dict[str, str]]]:
    value = json.loads((_repo_root() / CHECKLIST_PATH).read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _gate_stage_checklist_by_id(source_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    gate = source_payload.get("gate_challenger") if isinstance(source_payload.get("gate_challenger"), dict) else {}
    checklist = gate.get("stage_checklist") if isinstance(gate.get("stage_checklist"), list) else []
    result: dict[str, dict[str, Any]] = {}
    for item in checklist:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            result[item["id"]] = item
            canonical_id = _canonical_required_element_id(item["id"])
            if canonical_id != item["id"]:
                result[canonical_id] = item
    return result


def _generated_required_elements_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = payload.get("required_elements") if isinstance(payload.get("required_elements"), list) else []
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            result[item["id"]] = item
            canonical_id = _canonical_required_element_id(item["id"])
            if canonical_id != item["id"]:
                result[canonical_id] = item
    return result


def _required_element_status(
    item: dict[str, Any] | None,
    *,
    item_id: str,
    generated_item: dict[str, Any] | None,
    required_details: dict[str, Any],
) -> str:
    generated_status = str((generated_item or {}).get("status") or "").strip().lower()
    progress_groups = {
        "progress_review_next_half_year_plan": ("next_review_plan", "outputs_until_next_review", "metrics_until_next_review"),
        "progress_review_plan_fact_last_half_year": ("plan_fact", "launches", "metrics"),
        "stream_review_2_plus_plan_fact_last_half_year": ("plan_fact", "launches", "metrics"),
    }
    if item_id in progress_groups:
        detail_type, first_group, second_group = progress_groups[item_id]
        detail = required_details.get(item_id)
        if isinstance(detail, dict) and detail.get("type") == detail_type:
            present_groups = bool(detail.get(first_group)) + bool(detail.get(second_group))
            return ("нет", "частично подтверждено", "есть")[present_groups]
    if item_id == "gate2_user_flow":
        detail = required_details.get(item_id)
        if isinstance(detail, dict) and detail.get("type") == "source_links" and detail.get("links"):
            return "есть"
    if item_id == "gate2_value_proposition":
        generated_evidence = _non_empty_string((generated_item or {}).get("evidence"))
        if generated_status in {"есть", "present"} and generated_evidence:
            return "есть"
    if item_id.endswith("_stop_criteria"):
        detail = required_details.get(item_id)
        if isinstance(detail, dict) and (detail.get("primary_criterion") or detail.get("criteria")):
            return "есть"
        if generated_status in {"есть", "present", "частично подтверждено", "partially confirmed"} and _non_empty_string((generated_item or {}).get("evidence")):
            return "есть"
        if str((item or {}).get("status") or "").lower() in {"green", "present", "yellow", "partial"}:
            return "есть"
        return "нет"
    if item_id in {"gate2_hypothesis_results", "stream_review_1_solution_validation"}:
        detail = required_details.get(item_id)
        if isinstance(detail, dict) and detail.get("type") == "solution_validation":
            items = detail.get("items")
            if isinstance(items, list) and items:
                confirmed = sum(entry.get("verdict") == "confirmed" for entry in items if isinstance(entry, dict))
                return f"{confirmed}/{len(items)}"
        return "нет"

    if item_id in {"gate2_metric_linkage", "stream_review_1_input_output_metric_link"}:
        detail = required_details.get(item_id)
        if isinstance(detail, dict) and detail.get("type") == "metric_binding":
            metrics = [
                metric for key in ("input_metrics", "output_metrics")
                for metric in (detail.get(key) or [])
                if isinstance(metric, dict)
            ]
            if metrics:
                confirmed = sum(metric.get("binding") == "confirmed" for metric in metrics)
                if confirmed * 5 >= len(metrics) * 4:
                    return "есть"
                return "частично подтверждено" if confirmed else "нет"
        return "нет"

    status = str((item or {}).get("status") or "").lower()
    if status in {"present", "green", "true", "yes", "есть"}:
        return "есть"
    if status in {"yellow", "partial", "partially_confirmed", "частично подтверждено"}:
        return "частично подтверждено"
    return "нет"


def _required_element_evidence(
    item: dict[str, Any] | None,
    generated_item: dict[str, Any] | None,
    *,
    target_language: str,
) -> str | None:
    generated_evidence = (generated_item or {}).get("evidence")
    boilerplate = {"no evidence is provided.", "нет данных.", "раздел есть.", "the section is present."}
    if isinstance(generated_evidence, str) and generated_evidence.strip() and generated_evidence.strip().lower() not in boilerplate:
        return generated_evidence.strip()
    evidence = (item or {}).get("evidence")
    if target_language == "ru" and isinstance(evidence, str) and evidence.strip() and evidence.strip().lower() not in boilerplate:
        return evidence.strip()
    return None


def _canonical_required_element_id(item_id: str) -> str:
    aliases = {
        "gate1_primary_traction": "gate1_initial_traction",
        "gate1_hypotheses_metrics_thresholds": "gate1_hypotheses_with_metrics",
        "gate2_unique_value_proposition": "gate2_value_proposition",
        "gate2_mvp_or_target_product": "gate2_target_product",
        "gate2_input_output_metric_link": "gate2_metric_linkage",
        "gate2_metric_linkage_to_product": "gate2_metric_linkage",
        "gate2_mockups_or_user_flow": "gate2_user_flow",
        "gate2_gate3_commitments": "gate2_commitments",
        "gate3_mvp_hypothesis_confirmation": "gate3_solution_hypothesis_validation",
        "stream_review_1_metric_linkage_to_problem": "stream_review_1_input_output_metric_link",
        "stream_review_2_plus_next_half_year_plan": "progress_review_next_half_year_plan",
        "stream_review_2_plus_stop_criteria": "progress_review_stop_criteria",
        "stream_review_2_plus_plan_fact_last_half_year": "progress_review_plan_fact_last_half_year",
    }
    return aliases.get(item_id, item_id)


def _skill_text() -> str:
    return (_repo_root() / SKILL_PATH).read_text(encoding="utf-8")


def _new_summary_schema() -> dict[str, Any]:
    return json.loads((_repo_root() / SCHEMA_PATH).read_text(encoding="utf-8"))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _combined_raw_output(results: list[AnalysisProviderResult]) -> str:
    return "\n\n--- NEW SUMMARY PROVIDER ATTEMPT ---\n\n".join(
        result.raw_output for result in results if result.raw_output
    )


def _sum_optional(results: list[AnalysisProviderResult], attr: str) -> Any:
    values = [getattr(result, attr) for result in results if getattr(result, attr) is not None]
    if not values:
        return None
    return sum(values)


def public_new_summary_error_message(exc: BaseException) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return f"new_summary_generation_failed:invalid_json:{exc.lineno}:{exc.colno}"
    if isinstance(exc, ValidationError):
        return f"new_summary_generation_failed:schema_validation:{_json_path(exc.path)}"
    status_code = getattr(exc, "status_code", None)
    if status_code == 400 or exc.__class__.__name__ == "BadRequestError":
        return "new_summary_generation_failed:provider_bad_request"
    return f"new_summary_generation_failed:{exc.__class__.__name__}"


def _log_new_summary_phase(phase: str, context: dict[str, Any]) -> None:
    worker_logger.info(
        "new_summary_generation_phase",
        extra={
            "job_type": "run_summary_localizations",
            "phase": phase,
            **_diagnostic_safe_context(context),
        },
    )


def _log_new_summary_failure(exc: BaseException, context: dict[str, Any]) -> None:
    worker_logger.info(
        "new_summary_generation_diagnostic",
        extra={
            "job_type": "run_summary_localizations",
            "error_class": exc.__class__.__name__,
            "public_error": public_new_summary_error_message(exc),
            "error_message_length": len(str(exc)),
            "error_message_sha256": hashlib.sha256(str(exc).encode("utf-8", errors="replace")).hexdigest(),
            "json_error_line": exc.lineno if isinstance(exc, json.JSONDecodeError) else None,
            "json_error_column": exc.colno if isinstance(exc, json.JSONDecodeError) else None,
            "validation_path": _json_path(exc.path) if isinstance(exc, ValidationError) else None,
            "validation_schema_path": _json_path(exc.schema_path) if isinstance(exc, ValidationError) else None,
            "validation_validator": exc.validator if isinstance(exc, ValidationError) else None,
            "traceback": _safe_traceback(exc),
            **_diagnostic_safe_context(context),
        },
    )


def _new_summary_error_diagnostics(exc: BaseException, context: dict[str, Any]) -> dict[str, Any]:
    diagnostics = {
        **_diagnostic_safe_context(context),
        "error_class": exc.__class__.__name__,
        "error_module": exc.__class__.__module__,
        "public_error": public_new_summary_error_message(exc),
        "error_message_length": len(str(exc)),
        "error_message_sha256": hashlib.sha256(str(exc).encode("utf-8", errors="replace")).hexdigest(),
        "traceback": _safe_traceback(exc),
    }
    provider_error = _safe_provider_error_details(exc)
    if provider_error:
        diagnostics["provider_error"] = provider_error
    if isinstance(exc, json.JSONDecodeError):
        diagnostics["json_error_line"] = exc.lineno
        diagnostics["json_error_column"] = exc.colno
    if isinstance(exc, ValidationError):
        diagnostics["validation_path"] = _json_path(exc.path)
        diagnostics["validation_schema_path"] = _json_path(exc.schema_path)
        diagnostics["validation_validator"] = exc.validator
    return diagnostics


def _safe_provider_error_details(exc: BaseException) -> dict[str, Any] | None:
    details: dict[str, Any] = {}
    for attribute in ("status_code", "code", "type", "param"):
        value = getattr(exc, attribute, None)
        if isinstance(value, str | int):
            details[attribute] = value
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error") if isinstance(body.get("error"), dict) else body
        for source_key, target_key in (("code", "body_code"), ("type", "body_type"), ("param", "body_param")):
            value = error.get(source_key)
            if isinstance(value, str | int):
                details[target_key] = value
        message = error.get("message")
        if isinstance(message, str):
            details["body_message_length"] = len(message)
            details["body_message_sha256"] = hashlib.sha256(
                message.encode("utf-8", errors="replace")
            ).hexdigest()
    return details or None


def _provider_attempt_diagnostics(results: list[AnalysisProviderResult]) -> list[dict[str, Any]]:
    return [
        {
            "attempt": index,
            "raw_output_chars": len(result.raw_output or ""),
            "structured_text_chars": len(result.structured_text or ""),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "latency_ms": result.latency_ms,
            "estimated_cost": str(result.estimated_cost) if result.estimated_cost is not None else None,
        }
        for index, result in enumerate(results, start=1)
    ]


def _diagnostic_safe_context(context: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    allowed_scalars = {
        "analysis_id",
        "check_run_id",
        "step_id",
        "provider",
        "model",
        "document_stage",
        "document_type",
        "phase",
        "public_error",
        "attempt",
        "attempt_count",
        "prompt_chars",
        "schema_chars",
        "schema_path",
        "skill_path",
        "source_fingerprint",
        "source_payload_chars",
        "source_document_excerpt_chars",
        "provider_raw_output_present",
    }
    for key in allowed_scalars:
        value = context.get(key)
        if isinstance(value, str | int | float | bool) or value is None:
            safe[key] = value
    if isinstance(context.get("source_sections"), list):
        safe["source_sections"] = [str(item) for item in context["source_sections"]]
    if isinstance(context.get("attempts"), list):
        safe["attempts"] = context["attempts"]
    if isinstance(context.get("ru_payload_keys"), list):
        safe["ru_payload_keys"] = [str(item) for item in context["ru_payload_keys"]]
    if isinstance(context.get("en_payload_keys"), list):
        safe["en_payload_keys"] = [str(item) for item in context["en_payload_keys"]]
    if isinstance(context.get("payload_keys"), list):
        safe["payload_keys"] = [str(item) for item in context["payload_keys"]]
    if isinstance(context.get("provider_error"), dict):
        safe["provider_error"] = context["provider_error"]
    if isinstance(context.get("traceback"), list):
        safe["traceback"] = context["traceback"]
    return safe


def _safe_traceback(exc: BaseException) -> list[dict[str, Any]]:
    frames = traceback.extract_tb(exc.__traceback__ or None)
    return [
        {
            "file": Path(frame.filename).name,
            "line": frame.lineno,
            "function": frame.name,
        }
        for frame in frames[-8:]
    ]


def _json_path(path: Any) -> str:
    parts = [str(part) for part in path]
    return ".".join(parts) if parts else "$"

from __future__ import annotations

import hashlib
import json
import traceback
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging import worker_logger
from app.models.analysis import Analysis, AnalysisCheckRun, AnalysisDetailRun
from app.models.document import Document
from app.schemas.enums import Provider, RunStatus
from app.services.new_summaries import (
    NEW_SUMMARY_GENERATION_MODE,
    NEW_SUMMARY_VERSION,
    mark_new_summary_failed,
    mark_new_summary_progress,
    mark_new_summary_running,
    persist_new_summary_variant,
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
from skills.result_synthesis_trace import (
    complete_result_synthesis_step,
    fail_result_synthesis_step,
    start_result_synthesis_step,
)


LANGUAGES = ("ru", "en")
MAX_OUTPUT_TOKENS = 12000
SOURCE_DOCUMENT_MAX_CHARS = 16000
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
    anonymized_source_payload = (
        anonymization.value if isinstance(anonymization.value, dict) else source_payload
    )
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
        _log_new_summary_failure(
            exc,
            {
                **diagnostic_context,
                "phase": "generation_failed",
                "public_error": public_error,
                "attempt_count": len(provider_results),
                "attempts": _provider_attempt_diagnostics(provider_results),
            },
        )
        fail_result_synthesis_step(
            session=session,
            step=step,
            error_message=public_error,
            raw_output=_combined_raw_output(provider_results),
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
    return payload


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
    return {
        "initiative_title": _initiative_title(analysis=analysis, document=document),
        "document_stage": stage,
        "document_type": document_type,
        "source_document": _source_document_payload(document),
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
            return value.strip()
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
    return {
        "title": document.title,
        "original_filename": document.original_filename,
        "detected_document_type": document.detected_document_type,
        "manual_document_type": document.manual_document_type,
        "parsed_text_excerpt": _bounded_source_text(parsed_text),
    }


def _bounded_source_text(value: str) -> str:
    if len(value) <= SOURCE_DOCUMENT_MAX_CHARS:
        return value
    excerpt = value[:SOURCE_DOCUMENT_MAX_CHARS]
    boundary = excerpt.rfind("\n")
    if boundary > SOURCE_DOCUMENT_MAX_CHARS // 2:
        excerpt = excerpt[:boundary]
    return excerpt.rstrip() + "\n\n[TRUNCATED: source document excerpt was shortened for Summary generation.]"


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
            "Если в источниках нет Traction Summary с числами, не выдумывай значения: используй один период `Not provided`/`Не указано`, одну строку и пустые значения.",
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
        normalized_version["required_elements"] = _required_elements_from_source(
            source_payload=source_payload,
            target_language=expected_language,
            generated_payload=version,
        )
        normalized_version["required_details"] = _normalized_required_details(version)
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
    normalized.setdefault("schema_version", "new-summary-v1")
    normalized.setdefault("language", "en")
    title = normalized.get("title")
    if not isinstance(title, str) or not title.strip():
        normalized["title"] = f"AI Summary {_source_initiative_title(source_payload)}"

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
            "confirmed",
            "insufficiently_confirmed",
            "critical_problems",
            "other",
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
    for key in ("required_elements", "confirmed", "insufficiently_confirmed", "critical_problems", "other"):
        if not isinstance(normalized.get(key), list):
            normalized[key] = []
    return normalized


def _filter_allowed_keys(value: dict[str, Any], *, allowed: set[str]) -> dict[str, Any]:
    return {key: _copy_jsonish(item) for key, item in value.items() if key in allowed}


def _source_initiative_title(source_payload: dict[str, Any]) -> str:
    title = source_payload.get("initiative_title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return "Untitled initiative"


def _normalize_traction_summary(value: Any, *, language: str) -> dict[str, Any]:
    if isinstance(value, dict):
        metric_label = value.get("metric_label")
        periods = value.get("periods")
        rows = value.get("rows")
        if isinstance(metric_label, str) and metric_label.strip() and isinstance(periods, list) and isinstance(rows, list):
            period_pairs = [
                (index, str(period).strip())
                for index, period in enumerate(periods)
                if str(period).strip()
            ]
            normalized_periods = [period for _, period in period_pairs]
            normalized_rows = [
                {
                    "label": str(row.get("label") or "").strip(),
                    "values": [
                        str(row.get("values", [])[index])
                        if isinstance(row.get("values"), list) and index < len(row.get("values", []))
                        else ""
                        for index, _ in period_pairs
                    ],
                }
                for row in rows
                if isinstance(row, dict) and str(row.get("label") or "").strip()
            ]
            if normalized_periods and normalized_rows:
                return {
                    "metric_label": metric_label.strip(),
                    "periods": normalized_periods,
                    "rows": normalized_rows,
                }
    period = "Не указано" if language == "ru" else "Not provided"
    return {
        "metric_label": "Revenue",
        "periods": [period],
        "rows": [{"label": "Total incremental output uplifts", "values": [""]}],
    }


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
) -> list[dict[str, str]]:
    document_type = source_payload.get("document_type")
    expected = _new_summary_stage_checklist_items(
        str(document_type) if isinstance(document_type, str) else None,
        output_language=target_language,
    )
    by_id = _gate_stage_checklist_by_id(source_payload)
    generated_by_id = _generated_required_elements_by_id(generated_payload)
    return [
        {
            "id": item_id,
            "label": label,
            "status": _required_element_status(by_id.get(item_id)),
            "evidence": _required_element_evidence(
                by_id.get(item_id),
                generated_by_id.get(item_id),
                target_language=target_language,
            ),
        }
        for item_id, label in expected
    ]


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
            normalized[_canonical_required_element_id(item_id)] = normalized_detail
    return normalized


def _normalized_required_detail(detail: Any) -> dict[str, Any] | None:
    if not isinstance(detail, dict):
        return None
    detail_type = detail.get("type")
    if detail_type == "solution_validation":
        detail_items = detail.get("items")
        if not isinstance(detail_items, list):
            return None
        items = [
            {"text": text, "verdict": verdict}
            for item in detail_items
            if isinstance(item, dict)
            for text in [_non_empty_string(item.get("text"))]
            for verdict in [_enum_value(item.get("verdict"), {"confirmed", "insufficient"})]
            if text is not None and verdict is not None
        ]
        return {"type": detail_type, "items": items} if items else None
    if detail_type == "metric_binding":
        return {
            "type": detail_type,
            "input_metrics": _normalized_metric_binding_items(detail.get("input_metrics")),
            "output_metrics": _normalized_metric_binding_items(detail.get("output_metrics")),
        }
    if detail_type == "next_review_plan":
        outputs = _non_empty_strings(detail.get("outputs_until_next_review"))
        metrics = _normalized_metric_plan_rows(detail.get("metrics_until_next_review"))
        if not outputs or not metrics:
            return None
        return {
            "type": detail_type,
            "outputs_until_next_review": outputs,
            "metrics_until_next_review": metrics,
        }
    if detail_type == "stop_criteria":
        criteria = _non_empty_strings(detail.get("criteria"))
        return {"type": detail_type, "criteria": criteria} if criteria else None
    return None


def _normalized_metric_binding_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {"metric": metric, "binding": binding, "evidence": evidence}
        for item in value
        if isinstance(item, dict)
        for metric in [_non_empty_string(item.get("metric"))]
        for binding in [_enum_value(item.get("binding"), {"confirmed", "insufficient"})]
        for evidence in [_non_empty_string(item.get("evidence"))]
        if metric is not None and binding is not None and evidence is not None
    ]


def _normalized_metric_plan_rows(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {"metric": metric, "current": current, "next_review": next_review}
        for item in value
        if isinstance(item, dict)
        for metric in [_non_empty_string(item.get("metric"))]
        for current in [_non_empty_string(item.get("current"))]
        for next_review in [_non_empty_string(item.get("next_review"))]
        if metric is not None and current is not None and next_review is not None
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


def _required_element_status(item: dict[str, Any] | None) -> str:
    status = str((item or {}).get("status") or "").lower()
    if status in {"present", "green", "true", "yes", "есть"}:
        return "есть"
    return "нет"


def _required_element_evidence(
    item: dict[str, Any] | None,
    generated_item: dict[str, Any] | None,
    *,
    target_language: str,
) -> str:
    generated_evidence = (generated_item or {}).get("evidence")
    if isinstance(generated_evidence, str) and generated_evidence.strip():
        return generated_evidence.strip()
    evidence = (item or {}).get("evidence")
    if target_language == "ru" and isinstance(evidence, str) and evidence.strip():
        return evidence.strip()
    return "Не найдено в чеклисте Gate Challenger." if target_language == "ru" else "Not found in the Gate Challenger checklist."


def _canonical_required_element_id(item_id: str) -> str:
    aliases = {
        "gate1_primary_traction": "gate1_initial_traction",
        "gate1_hypotheses_metrics_thresholds": "gate1_hypotheses_with_metrics",
        "gate2_unique_value_proposition": "gate2_value_proposition",
        "gate2_mvp_or_target_product": "gate2_target_product",
        "gate2_metric_linkage_to_product": "gate2_metric_linkage",
        "gate2_mockups_or_user_flow": "gate2_user_flow",
        "gate2_gate3_commitments": "gate2_commitments",
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
        "schema_path",
        "skill_path",
        "source_fingerprint",
        "source_document_excerpt_chars",
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

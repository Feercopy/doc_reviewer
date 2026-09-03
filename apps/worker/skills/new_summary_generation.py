from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis import Analysis, AnalysisCheckRun, AnalysisDetailRun
from app.models.document import Document
from app.schemas.enums import Provider, RunStatus
from app.services.new_summaries import (
    NEW_SUMMARY_GENERATION_MODE,
    NEW_SUMMARY_VERSION,
    mark_new_summary_failed,
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
    response_schema = _new_summary_schema()
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
    revision = str(check_run.id)
    for language in LANGUAGES:
        mark_new_summary_running(analysis=analysis, revision=revision, language=language)
    session.commit()

    provider_results: list[AnalysisProviderResult] = []
    try:
        payload = _run_generation_with_json_retry(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            prompt=prompt,
            response_schema=response_schema,
            run_parameters=run_parameters,
            attempt_results=provider_results,
        )
        payload = deanonymize_model_value(payload, metadata=run_parameters.get(RUN_PARAMETER_KEY))
        validate(instance=payload, schema=response_schema)
        payload = _validated_source_dependent_report(
            payload=payload,
            source_payload=source_payload,
            response_schema=response_schema,
        )
    except Exception as exc:
        session.rollback()
        fail_result_synthesis_step(
            session=session,
            step=step,
            error_message=str(exc),
            raw_output=_combined_raw_output(provider_results),
        )
        mark_new_summary_failed(
            analysis=analysis,
            revision=revision,
            language="ru",
            error_message=str(exc),
        )
        mark_new_summary_failed(
            analysis=analysis,
            revision=revision,
            language="en",
            error_message=str(exc),
        )
        session.commit()
        raise

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
        json.dumps(source_payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
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
    run_parameters: dict[str, Any],
    attempt_results: list[AnalysisProviderResult],
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
        return _validated_new_summary(result, response_schema)
    except (json.JSONDecodeError, ValidationError) as exc:
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
            run_parameters={**run_parameters, "new_summary_json_retry": True},
        )
        attempt_results.append(retry_result)
        return _validated_new_summary(retry_result, response_schema)


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
) -> dict[str, Any]:
    payload = parse_json_output(result.structured_text)
    validate(instance=payload, schema=response_schema)
    return payload


def _validated_source_dependent_report(
    *,
    payload: dict[str, Any],
    source_payload: dict[str, Any],
    response_schema: dict[str, Any],
) -> dict[str, Any]:
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
        normalized[_canonical_required_element_id(item_id)] = _copy_jsonish(detail)
    return normalized


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

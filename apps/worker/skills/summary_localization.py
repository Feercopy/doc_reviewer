from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from jsonschema import ValidationError, validate
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.analysis import Analysis, AnalysisCheckRun
from app.schemas.enums import Provider
from ic_review.role_runner import apply_ic_review_provider_defaults
from privacy.model_anonymization import (
    RUN_PARAMETER_KEY,
    anonymize_value_for_model,
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


SCHEMA_PATH = "contracts/schemas/summary-localization.schema.json"
MAX_OUTPUT_TOKENS = 8000
MAX_SEGMENT_CHARS = 4000
MAX_BATCH_CHARS = 12000
MAX_BATCH_SEGMENTS = 20
LANGUAGES = ("ru", "en")


def build_summary_payload(*, analysis: Analysis, check_run: AnalysisCheckRun, language: str) -> dict[str, Any]:
    output = analysis.structured_output or {}
    result = output.get("result") if isinstance(output.get("result"), dict) else {}
    markdown = _first_text(
        output.get("assessment_markdown"),
        output.get("native_markdown"),
        output.get("markdown"),
        output.get("output_markdown"),
        output.get("summary_markdown"),
    )
    return {
        "run_mode": "summary_localization",
        "language": language,
        "short_summary": _first_text(result.get("short_summary"), analysis.summary, output.get("summary")),
        "product_analysis_markdown": _product_summary_markdown(markdown),
        "stage_checklist": _stage_checklist(output.get("stage_checklist")),
        "financial_analysis": _financial_analysis(check_run.structured_output),
    }


def persist_native_summary(
    *,
    session: Session,
    analysis: Analysis,
    check_run: AnalysisCheckRun,
) -> tuple[str, dict[str, Any], str]:
    gate_language = "en" if (analysis.run_parameters or {}).get("output_language") == "en" else "ru"
    ic_output_language = (check_run.run_parameters or {}).get("output_language")
    ic_language = ic_output_language if ic_output_language in LANGUAGES else gate_language
    source_language = gate_language if gate_language == ic_language else "mixed"
    payload = build_summary_payload(analysis=analysis, check_run=check_run, language=gate_language)
    validate(instance=payload, schema=_summary_schema())
    fingerprint = summary_payload_fingerprint(payload)
    if source_language == "mixed":
        return source_language, payload, fingerprint
    state = _state_for_revision(analysis=analysis, revision=str(check_run.id))
    state[source_language] = {
        "status": "completed",
        "payload": payload,
        "error_message": None,
        "source_language": source_language,
        "source_fingerprint": fingerprint,
    }
    _persist_state(analysis, state)
    session.commit()
    return source_language, payload, fingerprint


def translate_and_persist_summary(
    *,
    session: Session,
    analysis: Analysis,
    check_run: AnalysisCheckRun,
    source_language: str,
    source_payload: dict[str, Any],
    target_language: str,
    provider: Provider,
    model: str,
    api_key: str | None,
    base_url: str | None,
) -> dict[str, Any]:
    paths = _translatable_paths(source_payload)
    source_segments, segment_contexts, path_plans = _translation_plan(source_payload, paths)
    anonymization = anonymize_value_for_model(
        source_segments,
        existing_metadata=(check_run.run_parameters or {}).get(RUN_PARAMETER_KEY)
        or (analysis.run_parameters or {}).get(RUN_PARAMETER_KEY),
    )
    segments = anonymization.value if isinstance(anonymization.value, dict) else source_segments
    batches = _translation_batches(segments)
    batch_prompts = []
    for batch_index, batch in enumerate(batches):
        response_schema = _translation_schema(language=target_language, segment_ids=list(batch))
        batch_prompts.append(
            _translation_prompt(
                source_language=source_language,
                target_language=target_language,
                segments=batch,
                segment_contexts={segment_id: segment_contexts[segment_id] for segment_id in batch},
                response_schema=response_schema,
                batch_index=batch_index,
                batch_count=len(batches),
            )
        )
    prompt = "\n\n--- TRANSLATION BATCH ---\n\n".join(batch_prompts)
    run_parameters = dict(check_run.run_parameters or {})
    mock_results = run_parameters.get("summary_localization_mock_provider_results")
    if isinstance(mock_results, dict) and isinstance(mock_results.get(target_language), dict):
        run_parameters["mock_provider_result"] = mock_results[target_language]
    apply_ic_review_provider_defaults(run_parameters)
    run_parameters["max_output_tokens"] = MAX_OUTPUT_TOKENS
    run_parameters["max_retries"] = max(1, int(run_parameters.get("max_retries") or 0))
    run_parameters["summary_localization_language"] = target_language
    run_parameters["summary_localization_batch_count"] = len(batches)
    run_parameters["summary_localization_provider"] = provider.value
    run_parameters["summary_localization_model"] = model
    run_parameters[RUN_PARAMETER_KEY] = anonymization.metadata
    step = start_result_synthesis_step(
        session=session,
        check_run=check_run,
        step_name=f"summary_localization_{target_language}",
        prompt=prompt,
        run_parameters=run_parameters,
        skill=None,
        fallback_skill_metadata={
            "name": "summary_localization",
            "version": "2",
            "source_type": "inline_prompt",
            "result_schema_path": SCHEMA_PATH,
        },
    )
    mark_localization_running(
        session=session,
        analysis=analysis,
        check_run=check_run,
        language=target_language,
    )
    provider_results: list[AnalysisProviderResult] = []
    try:
        translated_segments: dict[str, str] = {}
        for batch_index, (batch, batch_prompt) in enumerate(zip(batches, batch_prompts, strict=True)):
            response_schema = _translation_schema(language=target_language, segment_ids=list(batch))
            translated = _run_translation_batch_with_json_retry(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                prompt=batch_prompt,
                response_schema=response_schema,
                run_parameters=run_parameters,
                batch_index=batch_index,
                batch_segments=batch,
                attempt_results=provider_results,
            )
            translated_segments.update(translated["translations"])
        translated_segments = deanonymize_model_value(
            translated_segments,
            metadata=run_parameters.get(RUN_PARAMETER_KEY),
        )
        payload = deepcopy(source_payload)
        payload["language"] = target_language
        for path, parts in path_plans.items():
            translated_text = "".join(
                translated_segments[value] if kind == "segment" else value
                for kind, value in parts
            )
            _set_path(payload, path, translated_text)
        validate(instance=payload, schema=_summary_schema())
    except Exception as exc:
        session.rollback()
        fail_result_synthesis_step(
            session=session,
            step=step,
            error_message=str(exc),
            raw_output=_combined_raw_output(provider_results),
        )
        raise

    state = _state_for_revision(analysis=analysis, revision=str(check_run.id))
    state[target_language] = {
        "status": "completed",
        "payload": payload,
        "error_message": None,
        "source_language": source_language,
        "source_fingerprint": summary_payload_fingerprint(source_payload),
        "trace_step_id": str(step.id),
    }
    _persist_state(analysis, state)
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
    return payload


def mark_localization_running(*, session: Session, analysis: Analysis, check_run: AnalysisCheckRun, language: str) -> None:
    state = _state_for_revision(analysis=analysis, revision=str(check_run.id))
    state[language] = {
        "status": "running",
        "payload": None,
        "error_message": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    _persist_state(analysis, state)
    session.commit()


def mark_localization_failed(
    *, session: Session, analysis: Analysis, check_run: AnalysisCheckRun, language: str, error_message: str
) -> None:
    session.rollback()
    current = session.get(Analysis, analysis.id)
    if current is None:
        return
    state = _state_for_revision(analysis=current, revision=str(check_run.id))
    state[language] = {"status": "failed", "payload": None, "error_message": error_message[:1000]}
    _persist_state(current, state)
    session.commit()


def _financial_analysis(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("run_mode") != "ic_agentic_review_compact":
        return None
    keys = (
        "run_mode",
        "verdict",
        "executive_brief",
        "confidence",
        "top_findings",
        "key_numbers",
        "spreadsheet_audit",
        "critical_risks",
        "data_gaps",
        "required_actions",
        "questions_for_team",
        "validation",
    )
    return {key: deepcopy(value[key]) for key in keys if key in value}


def _stage_checklist(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {key: str(item[key]) for key in ("id", "label", "status", "evidence")}
        for item in value
        if isinstance(item, dict) and all(item.get(key) is not None for key in ("id", "label", "status", "evidence"))
    ]


def _product_summary_markdown(markdown: str | None) -> str | None:
    if not markdown:
        return None
    value = markdown.strip()
    lines = value.splitlines()
    first = re.sub(r"^#{1,6}\s+", "", lines[0]).strip() if lines else ""
    if first in {"Оценка документа", "Document assessment"}:
        value = "\n".join(lines[1:]).lstrip()
    stop = re.search(
        r"^#{1,6}\s+(?:IC\s+Recommendations|IC\s+Recomendations|IC\s+рекомендации|Рекомендации\s+IC)\b",
        value,
        re.IGNORECASE | re.MULTILINE,
    )
    if stop:
        value = value[: stop.start()].strip()
    excluded = re.compile(
        r"^(#{1,6})\s+(?:Рекомендация инвестиционного комитета|Что (?:можно|нужно) улучшить в документе)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = excluded.search(value)
    while match:
        level = len(match.group(1))
        following = value[match.end() :]
        next_heading = re.search(r"^#{1," + str(level) + r"}\s+.+$", following, re.MULTILINE)
        end = len(value) if next_heading is None else match.end() + next_heading.start()
        value = (value[: match.start()].rstrip() + "\n\n" + value[end:].lstrip()).strip()
        match = excluded.search(value)
    return value or None


def _translatable_paths(payload: dict[str, Any]) -> list[tuple[str | int, ...]]:
    paths: list[tuple[str | int, ...]] = []
    for key in ("short_summary", "product_analysis_markdown"):
        if isinstance(payload.get(key), str) and payload[key].strip():
            paths.append((key,))
    for index, item in enumerate(payload["stage_checklist"]):
        paths.extend(("stage_checklist", index, key) for key in ("label", "evidence") if item.get(key))
    financial = payload.get("financial_analysis")
    if not isinstance(financial, dict):
        return paths
    paths.append(("financial_analysis", "executive_brief"))
    for index, item in enumerate(financial.get("top_findings") or []):
        paths.extend(("financial_analysis", "top_findings", index, key) for key in ("title", "summary", "evidence", "recommendation"))
    for index, item in enumerate(financial.get("key_numbers") or []):
        paths.extend(("financial_analysis", "key_numbers", index, key) for key in ("label", "unit", "source"))
    paths.append(("financial_analysis", "spreadsheet_audit", "summary"))
    paths.append(("financial_analysis", "validation", "summary"))
    for key in ("critical_risks", "data_gaps", "required_actions", "questions_for_team"):
        paths.extend(("financial_analysis", key, index) for index, _ in enumerate(financial.get(key) or []))
    return [path for path in paths if isinstance(_get_path(payload, path), str)]


def _translation_plan(
    payload: dict[str, Any],
    paths: list[tuple[str | int, ...]],
) -> tuple[dict[str, str], dict[str, str], dict[tuple[str | int, ...], list[tuple[str, str]]]]:
    segments: dict[str, str] = {}
    contexts: dict[str, str] = {}
    plans: dict[tuple[str | int, ...], list[tuple[str, str]]] = {}
    next_index = 0
    for path in paths:
        path_parts: list[tuple[str, str]] = []
        for kind, value in _bounded_text_parts(_get_path(payload, path)):
            if kind == "literal":
                path_parts.append((kind, value))
                continue
            segment_id = f"s{next_index:04d}"
            next_index += 1
            segments[segment_id] = value
            contexts[segment_id] = ".".join(str(part) for part in path)
            path_parts.append(("segment", segment_id))
        plans[path] = path_parts
    return segments, contexts, plans


def _bounded_text_parts(text: str) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = []
    for paragraph_part in re.split(r"(\n{2,})", text):
        if not paragraph_part:
            continue
        if re.fullmatch(r"\n{2,}", paragraph_part):
            parts.append(("literal", paragraph_part))
            continue
        _append_bounded_part(parts, paragraph_part)
    return parts


def _append_bounded_part(parts: list[tuple[str, str]], value: str) -> None:
    if not value.strip():
        parts.append(("literal", value))
        return
    leading = re.match(r"^\s*", value).group(0)
    trailing = re.search(r"\s*$", value).group(0)
    core_end = len(value) - len(trailing) if trailing else len(value)
    core = value[len(leading) : core_end]
    if leading:
        parts.append(("literal", leading))
    while len(core) > MAX_SEGMENT_CHARS:
        boundary = _last_whitespace_boundary(core, MAX_SEGMENT_CHARS)
        if boundary is None:
            parts.append(("segment", core[:MAX_SEGMENT_CHARS]))
            core = core[MAX_SEGMENT_CHARS:]
            continue
        start, end = boundary
        if start > 0:
            parts.append(("segment", core[:start]))
        parts.append(("literal", core[start:end]))
        core = core[end:]
    if core:
        parts.append(("segment", core))
    if trailing:
        parts.append(("literal", trailing))


def _last_whitespace_boundary(value: str, limit: int) -> tuple[int, int] | None:
    matches = list(re.finditer(r"\s+", value[: limit + 1]))
    if not matches:
        return None
    match = matches[-1]
    if match.start() == 0:
        return None
    return match.start(), match.end()


def _translation_batches(segments: dict[str, str]) -> list[dict[str, str]]:
    if not segments:
        return [{}]
    batches: list[dict[str, str]] = []
    current: dict[str, str] = {}
    current_chars = 0
    for segment_id, value in segments.items():
        if current and (
            len(current) >= MAX_BATCH_SEGMENTS
            or current_chars + len(value) > MAX_BATCH_CHARS
        ):
            batches.append(current)
            current = {}
            current_chars = 0
        current[segment_id] = value
        current_chars += len(value)
    if current:
        batches.append(current)
    return batches


def _run_translation_batch_with_json_retry(
    *,
    provider: Provider,
    model: str,
    api_key: str | None,
    base_url: str | None,
    prompt: str,
    response_schema: dict[str, Any],
    run_parameters: dict[str, Any],
    batch_index: int,
    batch_segments: dict[str, str],
    attempt_results: list[AnalysisProviderResult],
) -> dict[str, Any]:
    result = _call_translation_provider(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        prompt=prompt,
        response_schema=response_schema,
        run_parameters=_batch_run_parameters(
            run_parameters,
            batch_index=batch_index,
            batch_segments=batch_segments,
            retry=False,
        ),
    )
    attempt_results.append(result)
    try:
        return _validated_translation(result, response_schema)
    except (json.JSONDecodeError, ValidationError) as exc:
        retry_prompt = (
            prompt.rstrip()
            + "\n\nJSON RETRY: The previous response was incomplete or did not match the schema "
            + f"({exc.__class__.__name__}). Return exactly one complete JSON object and every required segment."
        )
        retry_result = _call_translation_provider(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            prompt=retry_prompt,
            response_schema=response_schema,
            run_parameters=_batch_run_parameters(
                run_parameters,
                batch_index=batch_index,
                batch_segments=batch_segments,
                retry=True,
            ),
        )
        attempt_results.append(retry_result)
        return _validated_translation(retry_result, response_schema)


def _call_translation_provider(
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


def _batch_run_parameters(
    run_parameters: dict[str, Any],
    *,
    batch_index: int,
    batch_segments: dict[str, str],
    retry: bool,
) -> dict[str, Any]:
    parameters = dict(run_parameters)
    parameters["summary_localization_batch"] = batch_index + 1
    parameters["summary_localization_json_retry"] = retry
    mock_key = (
        "summary_localization_json_retry_mock_provider_results"
        if retry
        else "summary_localization_mock_provider_results"
    )
    mock_results = parameters.get(mock_key)
    language = parameters.get("summary_localization_language")
    if isinstance(mock_results, dict) and isinstance(mock_results.get(language), dict):
        parameters["mock_provider_result"] = _bounded_mock_result(
            mock_results[language],
            segment_ids=list(batch_segments),
        )
    return parameters


def _bounded_mock_result(result: dict[str, Any], *, segment_ids: list[str]) -> dict[str, Any]:
    bounded = dict(result)
    try:
        payload = parse_json_output(str(result.get("structured_text") or ""))
    except json.JSONDecodeError:
        return bounded
    translations = payload.get("translations")
    if not isinstance(translations, dict):
        return bounded
    payload["translations"] = {
        segment_id: translations[segment_id]
        for segment_id in segment_ids
        if segment_id in translations
    }
    bounded["structured_text"] = json.dumps(payload, ensure_ascii=False)
    return bounded


def _validated_translation(result: AnalysisProviderResult, response_schema: dict[str, Any]) -> dict[str, Any]:
    translated = parse_json_output(result.structured_text)
    validate(instance=translated, schema=response_schema)
    return translated


def _translation_schema(*, language: str, segment_ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["run_mode", "language", "translations"],
        "additionalProperties": False,
        "properties": {
            "run_mode": {"type": "string", "const": "summary_localization_translation"},
            "language": {"type": "string", "const": language},
            "translations": {
                "type": "object",
                "required": segment_ids,
                "additionalProperties": False,
                "properties": {segment_id: {"type": "string"} for segment_id in segment_ids},
            },
        },
    }


def _translation_prompt(
    *,
    source_language: str,
    target_language: str,
    segments: dict,
    segment_contexts: dict,
    response_schema: dict,
    batch_index: int,
    batch_count: int,
) -> str:
    target_name = "Russian" if target_language == "ru" else "English"
    source_name = {"ru": "Russian", "en": "English", "mixed": "mixed Russian and English"}[source_language]
    return "\n\n".join(
        [
            f"Translate the provided {source_name} Summary text segments into {target_name}.",
            f"This is batch {batch_index + 1} of {batch_count}. Translate only the segments in this batch.",
            "Translate faithfully. Do not summarize, add conclusions, alter numbers, formulas, Markdown structure, placeholders, or evidence meaning. Preserve product names and proper nouns. Return every segment exactly once.",
            "Return one JSON object matching this schema, without Markdown fences:",
            json.dumps(response_schema, ensure_ascii=False, sort_keys=True),
            "Segment contexts (do not return these):",
            json.dumps(segment_contexts, ensure_ascii=False, sort_keys=True),
            "Segments:",
            json.dumps(segments, ensure_ascii=False, sort_keys=True),
        ]
    )


def _state_for_revision(*, analysis: Analysis, revision: str) -> dict[str, Any]:
    output = analysis.structured_output or {}
    result = output.get("result") if isinstance(output.get("result"), dict) else {}
    state = result.get("summary_localizations") if isinstance(result.get("summary_localizations"), dict) else {}
    if state.get("source_revision") != revision or state.get("version") != 1:
        return {
            "version": 1,
            "source_revision": revision,
            "ru": {"status": "queued", "payload": None, "error_message": None},
            "en": {"status": "queued", "payload": None, "error_message": None},
        }
    return deepcopy(state)


def _persist_state(analysis: Analysis, state: dict[str, Any]) -> None:
    output = dict(analysis.structured_output or {})
    result = dict(output.get("result") or {})
    result["summary_localizations"] = state
    output["result"] = result
    analysis.structured_output = output
    flag_modified(analysis, "structured_output")


def _summary_schema() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    return json.loads((root / SCHEMA_PATH).read_text(encoding="utf-8"))


def summary_payload_fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _combined_raw_output(results: list[AnalysisProviderResult]) -> str | None:
    if not results:
        return None
    return json.dumps(
        [result.raw_output or result.structured_text for result in results],
        ensure_ascii=False,
    )


def _sum_optional(results: list[AnalysisProviderResult], attribute: str) -> Any:
    values = [getattr(result, attribute) for result in results if getattr(result, attribute) is not None]
    return sum(values) if values else None


def _get_path(value: Any, path: tuple[str | int, ...]) -> Any:
    current = value
    for key in path:
        current = current[key]
    return current


def _set_path(value: Any, path: tuple[str | int, ...], replacement: str) -> None:
    current = value
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = replacement


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None

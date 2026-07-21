from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import validate
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.analysis import Analysis, AnalysisCheckRun
from app.models.skill import Skill
from app.schemas.enums import EntityStatus, Provider, RunStatus, SkillType
from ic_review.role_runner import apply_ic_review_provider_defaults
from providers.base import ProviderRunRequest
from providers.registry import get_provider_adapter
from results.schema_validation import parse_json_output
from skills.result_synthesis_trace import (
    complete_result_synthesis_step,
    fail_result_synthesis_step,
    start_result_synthesis_step,
)


RESULT_SUMMARY_SKILL_NAME = "result_summary_synthesis"
RESULT_SUMMARY_SCHEMA_PATH = "contracts/schemas/result-short-summary.schema.json"
RESULT_SUMMARY_MAX_OUTPUT_TOKENS = 1200
DEFAULT_RESULT_SUMMARY_PROMPT = """You are the Result tab short-summary synthesis skill.

Combine two already-produced review sections into one concise decision summary:
1. Gate Challenger Recommendations.
2. IC Review Executive Summary / Executive brief.

Write only the final short summary. Do not introduce new facts, scores, or evidence.
Preserve the strictest decision posture when the two sources disagree.
Prefer clear business language for an investment/product defense committee.
"""


def update_result_short_summary(
    *,
    session: Session,
    analysis: Analysis,
    check_run: AnalysisCheckRun,
    provider: Provider,
    model: str,
    api_key: str | None,
    base_url: str | None,
) -> str | None:
    if check_run.status != RunStatus.COMPLETED.value:
        return None

    gate_recommendations = extract_gate_challenger_recommendations(analysis.structured_output)
    ic_executive_summary = extract_ic_review_executive_summary(check_run.structured_output)
    if not gate_recommendations or not ic_executive_summary:
        _persist_result_summary_status(
            analysis=analysis,
            status="skipped",
            metadata={
                "reason": "source_section_missing",
                "has_gate_challenger_recommendations": bool(gate_recommendations),
                "has_ic_review_executive_summary": bool(ic_executive_summary),
                "ic_review_run_id": str(check_run.id),
            },
        )
        session.commit()
        return None

    skill = _resolve_result_summary_skill(session)
    schema = _load_schema(_skill_schema_path(skill))
    prompt = build_result_short_summary_prompt(
        gate_recommendations=gate_recommendations,
        ic_executive_summary=ic_executive_summary,
        output_language=(check_run.run_parameters or {}).get("output_language") or (analysis.run_parameters or {}).get("output_language"),
        skill_prompt=skill.prompt_text if skill else DEFAULT_RESULT_SUMMARY_PROMPT,
        response_schema=schema,
    )
    run_parameters = _result_summary_run_parameters(check_run.run_parameters or {})
    step = start_result_synthesis_step(
        session=session,
        check_run=check_run,
        step_name="result_short_summary",
        prompt=prompt,
        run_parameters=run_parameters,
        skill=skill,
        fallback_skill_metadata=_skill_metadata(skill),
    )
    raw_to_preserve = None
    try:
        result = get_provider_adapter(provider, run_parameters).run(
            ProviderRunRequest(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                prompt=prompt,
                response_schema=schema,
                run_parameters=run_parameters,
            )
        )
        raw_to_preserve = result.raw_output or result.structured_text
        payload = parse_json_output(result.structured_text)
        validate(instance=payload, schema=schema)
    except Exception as exc:
        session.rollback()
        fail_result_synthesis_step(
            session=session,
            step=step,
            error_message=str(exc),
            raw_output=raw_to_preserve,
        )
        raise

    complete_result_synthesis_step(
        session=session,
        step=step,
        raw_output=raw_to_preserve,
        structured_output=payload,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        latency_ms=result.latency_ms,
        estimated_cost=result.estimated_cost,
    )
    short_summary = str(payload["short_summary"]).strip()

    _persist_result_short_summary(
        analysis=analysis,
        short_summary=short_summary,
        metadata={
            "status": "completed",
            "skill": _skill_metadata(skill),
            "ic_review_run_id": str(check_run.id),
            "trace_step_id": str(step.id),
            "prompt_fingerprint": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "source_fingerprint": _source_fingerprint(
                gate_recommendations=gate_recommendations,
                ic_executive_summary=ic_executive_summary,
            ),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "latency_ms": result.latency_ms,
        },
    )
    session.commit()
    return short_summary


def build_result_short_summary_prompt(
    *,
    gate_recommendations: str,
    ic_executive_summary: str,
    output_language: str | None,
    skill_prompt: str,
    response_schema: dict,
) -> str:
    language_instruction = "Write in Russian." if output_language != "en" else "Write in English."
    return "\n\n".join(
        [
            skill_prompt.strip(),
            language_instruction,
            "Return exactly one JSON object matching the schema. No Markdown fences.",
            "Result Short Summary contract:",
            json.dumps(response_schema, ensure_ascii=False, sort_keys=True),
            "Source 1 - Gate Challenger Recommendations:",
            gate_recommendations.strip(),
            "Source 2 - IC Review Executive Summary:",
            ic_executive_summary.strip(),
        ]
    )


def extract_gate_challenger_recommendations(output: dict | None) -> str | None:
    if not isinstance(output, dict):
        return None

    direct = _first_text(
        output.get("recommendations"),
        output.get("recommendation"),
        output.get("required_actions"),
        output.get("next_steps"),
    )
    if direct:
        return direct

    markdown = _first_text(output.get("assessment_markdown"), output.get("summary_markdown"), output.get("markdown"))
    section = _extract_recommendation_section(markdown)
    return section or _first_text(output.get("summary"))


def extract_ic_review_executive_summary(output: dict | None) -> str | None:
    if not isinstance(output, dict):
        return None
    return _first_text(
        output.get("executive_brief"),
        output.get("executive_summary"),
        (output.get("narrative_summary") or {}).get("executive_summary") if isinstance(output.get("narrative_summary"), dict) else None,
        output.get("summary"),
    )


def _resolve_result_summary_skill(session: Session) -> Skill | None:
    return session.execute(
        select(Skill)
        .where(
            Skill.name == RESULT_SUMMARY_SKILL_NAME,
            Skill.skill_type == SkillType.RESULT_SUMMARY.value,
            Skill.status == EntityStatus.ACTIVE.value,
        )
        .order_by(Skill.created_at.desc())
    ).scalars().first()


def _result_summary_run_parameters(base_parameters: dict[str, Any]) -> dict[str, Any]:
    parameters = dict(base_parameters)
    mock_result = parameters.get("result_summary_mock_provider_result")
    if mock_result is not None:
        parameters["mock_provider_result"] = mock_result
    apply_ic_review_provider_defaults(parameters)
    parameters.setdefault("max_output_tokens", RESULT_SUMMARY_MAX_OUTPUT_TOKENS)
    parameters["result_summary_step"] = "short_summary_synthesis"
    return parameters


def _persist_result_short_summary(*, analysis: Analysis, short_summary: str, metadata: dict[str, Any]) -> None:
    output = dict(analysis.structured_output or {})
    result = dict(output.get("result") or {})
    result["short_summary"] = short_summary
    result["short_summary_status"] = "completed"
    result["short_summary_metadata"] = metadata
    output["result"] = result
    analysis.structured_output = output
    flag_modified(analysis, "structured_output")


def _persist_result_summary_status(*, analysis: Analysis, status: str, metadata: dict[str, Any]) -> None:
    output = dict(analysis.structured_output or {})
    result = dict(output.get("result") or {})
    result["short_summary_status"] = status
    result["short_summary_metadata"] = metadata
    output["result"] = result
    analysis.structured_output = output
    flag_modified(analysis, "structured_output")


def _skill_schema_path(skill: Skill | None) -> str:
    return skill.result_schema_path if skill else RESULT_SUMMARY_SCHEMA_PATH


def _load_schema(schema_path: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    return json.loads((root / schema_path).read_text(encoding="utf-8"))


def _skill_metadata(skill: Skill | None) -> dict[str, Any]:
    if skill is None:
        return {
            "name": RESULT_SUMMARY_SKILL_NAME,
            "version": "baseline",
            "skill_type": SkillType.RESULT_SUMMARY.value,
            "source_type": "inline_prompt",
            "result_schema_path": RESULT_SUMMARY_SCHEMA_PATH,
            "fallback": True,
        }
    return {
        "id": str(skill.id),
        "name": skill.name,
        "version": skill.version,
        "skill_type": skill.skill_type,
        "source_type": skill.source_type,
        "result_schema_path": skill.result_schema_path,
    }


def _source_fingerprint(*, gate_recommendations: str, ic_executive_summary: str) -> str:
    source_text = json.dumps(
        {
            "gate_challenger_recommendations": gate_recommendations,
            "ic_review_executive_summary": ic_executive_summary,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(source_text.encode("utf-8")).hexdigest()


def _extract_recommendation_section(markdown: str | None) -> str | None:
    if not markdown:
        return None
    lines = markdown.replace("\r\n", "\n").split("\n")
    start = None
    for index, line in enumerate(lines):
        if _is_recommendation_line(line):
            start = index
            break
    if start is None:
        return None

    collected: list[str] = []
    for offset, line in enumerate(lines[start:]):
        if offset > 0 and _looks_like_next_section(line):
            break
        collected.append(line)
    return _clean_text("\n".join(collected))


def _is_recommendation_line(line: str) -> bool:
    normalized = _normalize_heading(line)
    return bool(
        re.search(r"\b(recommendation|recommendations|ic recommendation|next steps)\b", normalized)
        or "рекомендац" in normalized
        or "следующие шаги" in normalized
    )


def _looks_like_next_section(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(r"^#{1,6}\s+", stripped):
        return True
    label_match = re.match(r"^(?:\*\*)?([^:*]{2,80}):(?!//)", stripped)
    if label_match:
        normalized_label = label_match.group(1).strip().lower()
        if not _is_recommendation_line(normalized_label) and normalized_label in {
            "why",
            "context",
            "evidence",
            "conclusion",
            "почему",
            "контекст",
            "доказательства",
            "итог",
            "вывод",
        }:
            return True
    if re.match(r"^(?:\*\*)?[\wА-Яа-яЁё][^:]{2,80}:(?:\*\*)?\s*$", stripped):
        return not _is_recommendation_line(stripped)
    return False


def _normalize_heading(value: str) -> str:
    return (
        value.strip()
        .replace("*", "")
        .replace("_", "")
        .replace("#", "")
        .replace(":", "")
        .lower()
    )


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _stringify_text(value)
        if text:
            return text
    return None


def _stringify_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, list):
        return _clean_text("\n".join(_stringify_text(item) or "" for item in value))
    if isinstance(value, dict):
        parts = []
        for key in ("title", "summary", "issue", "evidence", "recommendation", "action"):
            if key in value:
                parts.append(_stringify_text(value.get(key)) or "")
        if parts:
            return _clean_text("\n".join(parts))
        return _clean_text(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return _clean_text(str(value))


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\n{3,}", "\n\n", value.strip())
    return cleaned or None

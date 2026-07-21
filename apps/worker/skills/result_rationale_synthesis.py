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


RESULT_RATIONALE_SKILL_NAME = "result_rationale_synthesis"
RESULT_RATIONALE_SCHEMA_PATH = "contracts/schemas/result-rationale.schema.json"
RESULT_RATIONALE_MAX_OUTPUT_TOKENS = 3000
DEFAULT_RESULT_RATIONALE_PROMPT = """You are the Result tab rationale synthesis skill.

Combine two already-produced review sections:
1. Gate Challenger section "Почему оценка именно такая" / "Why this assessment".
2. IC Review Top findings.

Write the combined rationale in the same business-review style and structure as Gate Challenger's
"Почему оценка именно такая" section. Enrich the Gate Challenger rationale only with facts and
issues present in IC Review Top findings. Do not invent evidence, scores, or risks.
Also return structured rationale_items. Each item must represent one rationale subpoint and must
include sources:
- gate_challenger when the evidence for that subpoint is present in Source 1.
- ic_review when the evidence for that subpoint is present in Source 2.
- both values when both sources support the same subpoint.
Return Critical risks and Data gaps as separate lists copied or compressed from IC Review.
"""


def update_result_rationale(
    *,
    session: Session,
    analysis: Analysis,
    check_run: AnalysisCheckRun,
    provider: Provider,
    model: str,
    api_key: str | None,
    base_url: str | None,
) -> dict[str, Any] | None:
    if check_run.status != RunStatus.COMPLETED.value:
        return None

    gate_rationale = extract_gate_challenger_rationale(analysis.structured_output)
    ic_top_findings = extract_ic_review_top_findings(check_run.structured_output)
    critical_risks = extract_ic_review_text_list(check_run.structured_output, "critical_risks")
    data_gaps = extract_ic_review_text_list(check_run.structured_output, "data_gaps")
    if not gate_rationale or not ic_top_findings:
        _persist_result_rationale_status(
            analysis=analysis,
            status="skipped",
            metadata={
                "reason": "source_section_missing",
                "has_gate_challenger_rationale": bool(gate_rationale),
                "has_ic_review_top_findings": bool(ic_top_findings),
                "ic_review_run_id": str(check_run.id),
            },
        )
        session.commit()
        return None

    skill = _resolve_result_rationale_skill(session)
    schema = _load_schema(_skill_schema_path(skill))
    prompt = build_result_rationale_prompt(
        gate_rationale=gate_rationale,
        ic_top_findings=ic_top_findings,
        critical_risks=critical_risks,
        data_gaps=data_gaps,
        output_language=(check_run.run_parameters or {}).get("output_language") or (analysis.run_parameters or {}).get("output_language"),
        skill_prompt=skill.prompt_text if skill else DEFAULT_RESULT_RATIONALE_PROMPT,
        response_schema=schema,
    )
    run_parameters = _result_rationale_run_parameters(check_run.run_parameters or {})
    step = start_result_synthesis_step(
        session=session,
        check_run=check_run,
        step_name="result_rationale",
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

    _persist_result_rationale(
        analysis=analysis,
        rationale_markdown=str(payload["rationale_markdown"]).strip(),
        rationale_items=_normalize_rationale_items(payload.get("rationale_items")),
        critical_risks=[str(item).strip() for item in payload.get("critical_risks", []) if str(item).strip()],
        data_gaps=[str(item).strip() for item in payload.get("data_gaps", []) if str(item).strip()],
        metadata={
            "status": "completed",
            "skill": _skill_metadata(skill),
            "ic_review_run_id": str(check_run.id),
            "trace_step_id": str(step.id),
            "prompt_fingerprint": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "source_fingerprint": _source_fingerprint(
                gate_rationale=gate_rationale,
                ic_top_findings=ic_top_findings,
                critical_risks=critical_risks,
                data_gaps=data_gaps,
            ),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "latency_ms": result.latency_ms,
        },
    )
    session.commit()
    return payload


def build_result_rationale_prompt(
    *,
    gate_rationale: str,
    ic_top_findings: str,
    critical_risks: list[str],
    data_gaps: list[str],
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
            "Do not include the outer title 'Почему оценка именно такая'; the UI renders that title.",
            "For every rationale_items[] entry, set sources only from evidence actually present in the source blocks.",
            "Use sources ['gate_challenger', 'ic_review'] when both Source 1 and Source 2 support the item.",
            "Use only ['gate_challenger'] or only ['ic_review'] when only one source supports the item.",
            "Result Rationale contract:",
            json.dumps(response_schema, ensure_ascii=False, sort_keys=True),
            "Source 1 - Gate Challenger rationale:",
            gate_rationale.strip(),
            "Source 2 - IC Review Top findings:",
            ic_top_findings.strip(),
            "Source 3 - IC Review Critical risks:",
            json.dumps(critical_risks, ensure_ascii=False),
            "Source 4 - IC Review Data gaps:",
            json.dumps(data_gaps, ensure_ascii=False),
        ]
    )


def extract_gate_challenger_rationale(output: dict | None) -> str | None:
    if not isinstance(output, dict):
        return None

    direct = _first_text(
        output.get("rationale"),
        output.get("why_this_assessment"),
        output.get("assessment_rationale"),
    )
    if direct:
        return direct

    markdown = _first_text(output.get("assessment_markdown"), output.get("summary_markdown"), output.get("markdown"))
    section = _extract_named_section(markdown, _is_rationale_heading)
    return section or _first_text(output.get("summary"))


def extract_ic_review_top_findings(output: dict | None) -> str | None:
    if not isinstance(output, dict):
        return None
    findings = output.get("top_findings")
    if not isinstance(findings, list):
        return None
    lines = [_format_finding(item) for item in findings]
    return _clean_text("\n".join(line for line in lines if line))


def extract_ic_review_text_list(output: dict | None, key: str) -> list[str]:
    if not isinstance(output, dict):
        return []
    value = output.get(key)
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _stringify_text(item))]


def _resolve_result_rationale_skill(session: Session) -> Skill | None:
    return session.execute(
        select(Skill)
        .where(
            Skill.name == RESULT_RATIONALE_SKILL_NAME,
            Skill.skill_type == SkillType.RESULT_SUMMARY.value,
            Skill.status == EntityStatus.ACTIVE.value,
        )
        .order_by(Skill.created_at.desc())
    ).scalars().first()


def _result_rationale_run_parameters(base_parameters: dict[str, Any]) -> dict[str, Any]:
    parameters = dict(base_parameters)
    mock_result = parameters.get("result_rationale_mock_provider_result")
    if mock_result is not None:
        parameters["mock_provider_result"] = mock_result
    apply_ic_review_provider_defaults(parameters)
    parameters.setdefault("max_output_tokens", RESULT_RATIONALE_MAX_OUTPUT_TOKENS)
    parameters["result_rationale_step"] = "rationale_synthesis"
    return parameters


def _persist_result_rationale(
    *,
    analysis: Analysis,
    rationale_markdown: str,
    rationale_items: list[dict[str, Any]],
    critical_risks: list[str],
    data_gaps: list[str],
    metadata: dict[str, Any],
) -> None:
    output = dict(analysis.structured_output or {})
    result = dict(output.get("result") or {})
    result["rationale_markdown"] = rationale_markdown
    result["rationale_items"] = rationale_items
    result["critical_risks"] = critical_risks
    result["data_gaps"] = data_gaps
    result["rationale_status"] = "completed"
    result["rationale_metadata"] = metadata
    output["result"] = result
    analysis.structured_output = output
    flag_modified(analysis, "structured_output")


def _normalize_rationale_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized_items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        detail = str(item.get("detail") or "").strip()
        sources = [
            source
            for source in item.get("sources", [])
            if source in {"gate_challenger", "ic_review"}
        ] if isinstance(item.get("sources"), list) else []
        if title and detail and sources:
            normalized_items.append({"title": title, "detail": detail, "sources": sources})
    return normalized_items


def _persist_result_rationale_status(*, analysis: Analysis, status: str, metadata: dict[str, Any]) -> None:
    output = dict(analysis.structured_output or {})
    result = dict(output.get("result") or {})
    result["rationale_status"] = status
    result["rationale_metadata"] = metadata
    output["result"] = result
    analysis.structured_output = output
    flag_modified(analysis, "structured_output")


def _skill_schema_path(skill: Skill | None) -> str:
    return skill.result_schema_path if skill else RESULT_RATIONALE_SCHEMA_PATH


def _load_schema(schema_path: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    return json.loads((root / schema_path).read_text(encoding="utf-8"))


def _skill_metadata(skill: Skill | None) -> dict[str, Any]:
    if skill is None:
        return {
            "name": RESULT_RATIONALE_SKILL_NAME,
            "version": "baseline",
            "skill_type": SkillType.RESULT_SUMMARY.value,
            "source_type": "inline_prompt",
            "result_schema_path": RESULT_RATIONALE_SCHEMA_PATH,
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


def _source_fingerprint(
    *,
    gate_rationale: str,
    ic_top_findings: str,
    critical_risks: list[str],
    data_gaps: list[str],
) -> str:
    source_text = json.dumps(
        {
            "gate_challenger_rationale": gate_rationale,
            "ic_review_top_findings": ic_top_findings,
            "critical_risks": critical_risks,
            "data_gaps": data_gaps,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(source_text.encode("utf-8")).hexdigest()


def _extract_named_section(markdown: str | None, predicate) -> str | None:
    if not markdown:
        return None
    lines = markdown.replace("\r\n", "\n").split("\n")
    start = None
    for index, line in enumerate(lines):
        if predicate(line):
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


def _is_rationale_heading(line: str) -> bool:
    normalized = _normalize_heading(line)
    return bool(
        "почему оценка именно такая" in normalized
        or normalized in {"почему", "why"}
        or "why this assessment" in normalized
        or "why the assessment" in normalized
        or "rationale" in normalized
    )


def _looks_like_next_section(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(r"^#{1,6}\s+", stripped):
        return True
    if re.match(r"^(?:\*\*)?[\wА-Яа-яЁё][^:]{2,80}:(?:\*\*)?\s*$", stripped):
        return True
    label_match = re.match(r"^(?:\*\*)?([^:*]{2,80}):(?!//)", stripped)
    if label_match:
        normalized_label = label_match.group(1).strip().lower()
        return normalized_label in {
            "recommendation",
            "recommendations",
            "next steps",
            "evidence",
            "conclusion",
            "рекомендация",
            "рекомендации",
            "следующие шаги",
            "доказательства",
            "вывод",
            "итог",
        }
    return False


def _format_finding(item: Any) -> str | None:
    if not isinstance(item, dict):
        return _stringify_text(item)
    title = _stringify_text(item.get("title"))
    severity = _stringify_text(item.get("severity"))
    summary = _stringify_text(item.get("summary"))
    evidence = _stringify_text(item.get("evidence"))
    recommendation = _stringify_text(item.get("recommendation"))
    parts = [
        f"{title} - {severity}: {summary}" if title or severity or summary else "",
        f"Evidence: {evidence}" if evidence else "",
        f"Recommendation: {recommendation}" if recommendation else "",
    ]
    return _clean_text(". ".join(part for part in parts if part))


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
        return _clean_text("\n".join(str(item) for item in value if item is not None))
    if isinstance(value, dict):
        return _clean_text(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return _clean_text(str(value))


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\n{3,}", "\n\n", value.strip())
    return cleaned or None

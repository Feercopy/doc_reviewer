from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from ic_review.context import ICReviewContext


ROLE_ORDER = (
    "ic-financial-auditor",
    "ic-product-analyst",
    "ic-market-analyst",
    "ic-web-researcher",
    "ic-benchmark-valuation",
    "ic-team-legal",
    "ic-tech-dd",
    "ic-risk-scenario",
)

ROLE_SCHEMA_PATH = "contracts/schemas/ic-agentic-role-result.schema.json"
REVIEW_SCHEMA_PATH = "contracts/schemas/ic-agentic-review-result.schema.json"
SYNTHESIS_COMMAND_PATH = ".claude/commands/invest-analysis.md"


class SnapshotTextReader(Protocol):
    def read_text(self, relative_path: str) -> str | None:
        ...


def render_role_prompt(
    *,
    role: str,
    context: ICReviewContext,
    source_snapshot: SnapshotTextReader,
    role_schema: dict[str, Any] | None = None,
) -> str:
    if role not in ROLE_ORDER:
        raise ValueError(f"unsupported_ic_role:{role}")

    role_prompt = _read_required_snapshot_text(source_snapshot, f".claude/agents/{role}.md")
    schema = role_schema or _load_schema(ROLE_SCHEMA_PATH)
    sections = [
        "# IC Agentic Review Role Step",
        "## Original Role Instructions",
        role_prompt,
        "## Document Context",
        _json_block(
            {
                "document_title": context.document_title,
                "document_type": context.document_type,
                "parsed_document_text": context.parsed_document_text,
                "output_language": context.output_language,
            }
        ),
        "## Main Gate Challenger Result Context",
        _json_block(
            {
                "verdict": context.main_analysis_verdict,
                "summary": context.main_analysis_summary,
                "structured_output": context.main_analysis_structured_output,
                "detail_output": context.main_analysis_detail_output,
            }
        ),
    ]
    if context.workbook_extraction_summary is not None or context.formula_auditor_summary is not None:
        sections.extend(
            [
                "## Workbook Context",
                _json_block(
                    {
                        "workbook_extraction_summary": context.workbook_extraction_summary,
                        "formula_auditor_summary": context.formula_auditor_summary,
                    }
                ),
            ]
        )
    sections.extend(
        [
            "## Output Contract",
            (
                "Return only JSON matching `ic-agentic-role-result.schema.json`. "
                "Do not include Markdown fences, commentary, or prose outside the JSON object."
            ),
            _json_block(schema),
        ]
    )
    return "\n\n".join(sections).strip() + "\n"


def render_synthesis_prompt(
    *,
    context: ICReviewContext,
    role_outputs: dict[str, dict[str, Any]],
    source_snapshot: SnapshotTextReader,
    review_schema: dict[str, Any] | None = None,
) -> str:
    synthesis_instructions = _read_required_snapshot_text(source_snapshot, SYNTHESIS_COMMAND_PATH)
    schema = review_schema or _load_schema(REVIEW_SCHEMA_PATH)
    missing_roles = [role for role in ROLE_ORDER if role not in role_outputs or role_outputs[role] is None]
    if missing_roles:
        raise ValueError(f"missing_role_outputs:{','.join(missing_roles)}")
    ordered_role_outputs = {role: role_outputs.get(role) for role in ROLE_ORDER}
    return (
        "# IC Agentic Review Synthesis Step\n\n"
        "## Original Synthesis Instructions\n"
        f"{synthesis_instructions}\n\n"
        "## Document And Main Analysis Context\n"
        f"{_json_block(context.to_dict())}\n\n"
        "## Role Structured Outputs\n"
        f"{_json_block(ordered_role_outputs)}\n\n"
        "## Synthesis Requirements\n"
        "- Produce a compact UI result for the product interface.\n"
        "- Preserve a legacy-compatible JSON interpretation for deterministic post-processing artifacts.\n"
        "- Do not write direct report prose; the worker will save a text debug artifact from structured data.\n"
        "- Russian is the default output language unless the context output_language explicitly says otherwise.\n"
        "- Return only one JSON object with exactly two top-level keys: `compact_result` and `legacy_report_json`.\n"
        "- `compact_result` must match `ic-agentic-review-result.schema.json` exactly.\n"
        "- `legacy_report_json` must use the original legacy report shape with `meta`, `sections`, `scenarios`, "
        "`formula_issues`, `kpis`, `risks_structured`, and `appendices` when available.\n"
        "- Do not include Markdown fences, commentary, or prose outside that JSON object.\n\n"
        "## Compact Result Schema\n"
        f"{_json_block(schema)}\n"
    )


def _read_required_snapshot_text(source_snapshot: SnapshotTextReader, relative_path: str) -> str:
    text = source_snapshot.read_text(relative_path)
    if text is None:
        raise RuntimeError(f"source_snapshot_missing:{relative_path}")
    return text


def _load_schema(schema_path: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    return json.loads((root / schema_path).read_text(encoding="utf-8"))


def _json_block(payload: Any) -> str:
    return "```json\n" + json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n```"

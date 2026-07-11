from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

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


MAX_COMMON_EVIDENCE = 10
MAX_ROLE_EVIDENCE = 10
MAX_SYNTHESIS_EVIDENCE = 18
MAX_SNIPPET_CHARS = 900
MAX_CONTEXT_STRING_CHARS = 1600
MAX_CONTEXT_LIST_ITEMS = 12
MAX_CONTEXT_DICT_ITEMS = 24

ROLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ic-financial-auditor": (
        "arr",
        "burn",
        "cac",
        "cash",
        "ebitda",
        "gross margin",
        "irr",
        "ltv",
        "margin",
        "payback",
        "revenue",
        "runway",
        "unit economics",
        "выруч",
        "денеж",
        "марж",
        "окуп",
        "юнит",
    ),
    "ic-product-analyst": (
        "activation",
        "churn",
        "cohort",
        "conversion",
        "engagement",
        "funnel",
        "mau",
        "nps",
        "product",
        "retention",
        "user",
        "ворон",
        "когорт",
        "отток",
        "продукт",
        "удерж",
    ),
    "ic-market-analyst": (
        "cagr",
        "competition",
        "competitor",
        "market",
        "penetration",
        "sam",
        "segment",
        "share",
        "som",
        "tam",
        "конкур",
        "рын",
        "сегмент",
    ),
    "ic-web-researcher": (
        "customer",
        "external",
        "feedback",
        "partner",
        "press",
        "review",
        "source",
        "website",
        "клиент",
        "отзыв",
        "партнер",
    ),
    "ic-benchmark-valuation": (
        "benchmark",
        "comparable",
        "ev/",
        "multiple",
        "peer",
        "valuation",
        "vc",
        "оценк",
        "мультипл",
    ),
    "ic-team-legal": (
        "compliance",
        "contract",
        "gdpr",
        "legal",
        "license",
        "risk owner",
        "team",
        "terms",
        "закон",
        "команд",
        "лиценз",
        "прав",
        "юрид",
    ),
    "ic-tech-dd": (
        "api",
        "architecture",
        "data lineage",
        "integration",
        "monitoring",
        "reliability",
        "sla",
        "tech",
        "uptime",
        "архитект",
        "интеграц",
        "монитор",
        "тех",
    ),
    "ic-risk-scenario": (
        "assumption",
        "downside",
        "mitigation",
        "risk",
        "scenario",
        "sensitivity",
        "stress",
        "upside",
        "допущ",
        "риск",
        "сценар",
        "стресс",
    ),
}

COMMON_KEYWORDS = (
    "approval",
    "assumption",
    "blocker",
    "evidence",
    "finding",
    "gate",
    "kpi",
    "metric",
    "recommendation",
    "risk",
    "section",
    "verdict",
    "вывод",
    "доказ",
    "метрик",
    "риск",
)


@dataclass(frozen=True)
class ICReviewContextPack:
    format_version: str
    common: dict[str, Any]
    main_analysis_context: dict[str, Any]
    workbook_context: dict[str, Any] | None
    common_evidence: list[dict[str, Any]]
    role_evidence: dict[str, list[dict[str, Any]]]
    synthesis_evidence: list[dict[str, Any]]
    source_stats: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def for_role(self, role: str) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "role": role,
            "common": self.common,
            "main_analysis_context": self.main_analysis_context,
            "common_evidence": self.common_evidence,
            "role_evidence": self.role_evidence.get(role, []),
            "workbook_context": self.workbook_context,
            "source_stats": self.source_stats,
            "instructions": [
                "Use evidence_id values when grounding findings.",
                "Treat omitted source text as unavailable context, not as evidence that a fact is absent.",
                "Prefer document, main-analysis, workbook, and formula facts included in this pack.",
            ],
        }

    def for_synthesis(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "common": self.common,
            "main_analysis_context": self.main_analysis_context,
            "synthesis_evidence": self.synthesis_evidence,
            "workbook_context": self.workbook_context,
            "source_stats": self.source_stats,
            "instructions": [
                "Synthesize from role outputs first, then use this evidence index for traceability.",
                "Do not infer facts from source text that is not present in role outputs or this context pack.",
                "Keep the final compact result short and evidence-grounded.",
            ],
        }


def build_ic_review_context_pack(context: ICReviewContext) -> ICReviewContextPack:
    document_evidence = _extract_document_evidence(context.parsed_document_text)
    common_evidence = _select_evidence(
        document_evidence,
        keywords=COMMON_KEYWORDS,
        limit=MAX_COMMON_EVIDENCE,
    )
    role_evidence = {
        role: _select_evidence(
            document_evidence,
            keywords=ROLE_KEYWORDS.get(role, ()),
            limit=MAX_ROLE_EVIDENCE,
        )
        for role in ROLE_ORDER
    }
    synthesis_evidence = _select_evidence(
        document_evidence,
        keywords=COMMON_KEYWORDS + tuple(keyword for keywords in ROLE_KEYWORDS.values() for keyword in keywords),
        limit=MAX_SYNTHESIS_EVIDENCE,
    )

    return ICReviewContextPack(
        format_version="ic_review_context_pack_v1",
        common={
            "document_title": _bounded_text(context.document_title, 240),
            "document_type": context.document_type,
            "output_language": context.output_language,
        },
        main_analysis_context={
            "verdict": context.main_analysis_verdict,
            "summary": _bounded_text(context.main_analysis_summary, 1200),
            "structured_output": _compact_value(context.main_analysis_structured_output),
            "detail_output": _compact_value(context.main_analysis_detail_output),
        },
        workbook_context=_workbook_context(context),
        common_evidence=common_evidence,
        role_evidence=role_evidence,
        synthesis_evidence=synthesis_evidence,
        source_stats={
            "parsed_document_chars": len(context.parsed_document_text or ""),
            "document_evidence_count": len(document_evidence),
            "common_evidence_count": len(common_evidence),
            "role_evidence_limit": MAX_ROLE_EVIDENCE,
            "snippet_max_chars": MAX_SNIPPET_CHARS,
        },
    )


def _extract_document_evidence(text: str | None) -> list[dict[str, Any]]:
    if not text:
        return []
    snippets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in _candidate_chunks(text):
        normalized = _normalize_whitespace(chunk)
        if len(normalized) < 20 or normalized in seen:
            continue
        seen.add(normalized)
        bounded = _bounded_text(normalized, MAX_SNIPPET_CHARS)
        start = text.find(chunk)
        if start < 0:
            start = text.find(normalized[:80])
        end = start + len(chunk) if start >= 0 else None
        snippets.append(
            {
                "evidence_id": f"doc-{len(snippets) + 1:03d}",
                "source_type": "parsed_document",
                "section_hint": _section_hint(normalized),
                "char_start": start if start >= 0 else None,
                "char_end": end,
                "text": bounded,
            }
        )
    return snippets


def _candidate_chunks(text: str) -> list[str]:
    raw_parts = re.split(r"\n\s*\n|(?<=\.)\s+(?=(?:Section|Раздел|Глава)\s+\d+[:.\-])", text)
    chunks: list[str] = []
    for part in raw_parts:
        stripped = part.strip()
        if not stripped:
            continue
        if len(stripped) <= MAX_SNIPPET_CHARS * 2:
            chunks.append(stripped)
            continue
        chunks.extend(_split_long_chunk(stripped))
    return chunks


def _split_long_chunk(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(current) + len(sentence) + 1 <= MAX_SNIPPET_CHARS:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            current = sentence[:MAX_SNIPPET_CHARS]
    if current:
        chunks.append(current)
    return chunks


def _select_evidence(
    evidence: list[dict[str, Any]],
    *,
    keywords: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    scored = [
        (_evidence_score(item, keywords), index, item)
        for index, item in enumerate(evidence)
    ]
    selected = [
        item
        for score, _index, item in sorted(scored, key=lambda entry: (-entry[0], entry[1]))
        if score > 0
    ][:limit]
    if selected:
        return selected
    return evidence[: min(limit, 3)]


def _evidence_score(item: dict[str, Any], keywords: tuple[str, ...]) -> int:
    text = str(item.get("text") or "")
    lowered = text.lower()
    score = 0
    for keyword in keywords:
        if keyword.lower() in lowered:
            score += 5
    if re.search(r"\d", text):
        score += 3
    if re.search(r"[%$€₽]|\b(?:m|mln|bn|k|млн|млрд)\b", lowered):
        score += 2
    if item.get("section_hint"):
        score += 2
    if any(marker in lowered for marker in ("risk", "gap", "fail", "critical", "blocker", "риск", "нет ", "не ")):
        score += 2
    return score


def _workbook_context(context: ICReviewContext) -> dict[str, Any] | None:
    if context.workbook_extraction_summary is None and context.formula_auditor_summary is None:
        return None
    return {
        "workbook_extraction_summary": _compact_value(context.workbook_extraction_summary),
        "formula_auditor_summary": _compact_value(context.formula_auditor_summary),
    }


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return _bounded_text(value, MAX_CONTEXT_STRING_CHARS if depth < 2 else 700)
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, list):
        return [_compact_value(item, depth=depth + 1) for item in value[:MAX_CONTEXT_LIST_ITEMS]]
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in list(value.items())[:MAX_CONTEXT_DICT_ITEMS]:
            compact[str(key)] = _compact_value(item, depth=depth + 1)
        return compact
    return _bounded_text(str(value), 700)


def _bounded_text(value: str | None, max_chars: int) -> str:
    text = _normalize_whitespace(str(value or ""))
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _section_hint(text: str) -> str | None:
    match = re.search(r"\b(?:Section|Раздел|Глава)\s+\d+[A-Za-zА-Яа-я0-9 .:_-]*", text, flags=re.IGNORECASE)
    if not match:
        return None
    return _bounded_text(match.group(0), 120)

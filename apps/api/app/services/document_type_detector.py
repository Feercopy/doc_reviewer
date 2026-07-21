from dataclasses import dataclass
from decimal import Decimal

from app.schemas.enums import DocumentType


@dataclass(frozen=True)
class DocumentTypeDetection:
    document_type: DocumentType
    confidence: Decimal
    explanation: str


@dataclass(frozen=True)
class _DetectionRule:
    document_type: DocumentType
    exact_phrases: tuple[str, ...]
    supporting_keywords: tuple[str, ...]
    weak_phrases: tuple[str, ...] = ()


_RULES = (
    _DetectionRule(
        document_type=DocumentType.GATE_2,
        exact_phrases=("Gate 2",),
        supporting_keywords=(
            "Gate 1 continuity",
            "planned traction",
            "MLP",
            "MVP",
            "scope",
            "metrics",
            "risks",
            "business case",
            "Gate 3 commitments",
        ),
    ),
    _DetectionRule(
        document_type=DocumentType.STREAM_REVIEW_1,
        exact_phrases=("1st Stream Review", "Stream review 1", "SR 1"),
        supporting_keywords=(
            "discovery results",
            "validated product ideas",
            "planned traction",
            "resources",
            "roadmap",
            "IC readiness",
            "next SR",
        ),
        weak_phrases=("Stream review",),
    ),
    _DetectionRule(
        document_type=DocumentType.STREAM_REVIEW_2_PLUS,
        exact_phrases=("Stream review 2+", "2nd Stream Review", "SR 2+"),
        supporting_keywords=(
            "previous SR",
            "plan / fact",
            "backlog updates",
            "traction model changes",
            "resource assumptions",
            "next SR commitments",
            "traffic-light",
        ),
        weak_phrases=("Stream review",),
    ),
    _DetectionRule(
        document_type=DocumentType.GATE_3,
        exact_phrases=("Gate 3",),
        supporting_keywords=(
            "Gate 2",
            "MLP",
            "PMF",
            "Gate 4",
            "customer experience",
            "Contact Rate",
            "CSAT",
            "NPS",
            "baseline status",
        ),
    ),
)

_UNKNOWN_THRESHOLD = Decimal("0.45")


def detect_document_type(text: str) -> DocumentTypeDetection:
    normalized_text = text.casefold()
    scored_results = [_score_rule(rule, normalized_text) for rule in _RULES]
    scored_results.sort(key=lambda item: item[0], reverse=True)

    top_score, top_type, top_matches = scored_results[0]
    runner_up_score = scored_results[1][0] if len(scored_results) > 1 else Decimal("0.0")
    if top_score > 0 and top_score - runner_up_score < Decimal("0.15"):
        top_score = max(Decimal("0.0"), top_score - Decimal("0.2"))

    top_score = min(top_score, Decimal("0.95"))
    if top_score < _UNKNOWN_THRESHOLD:
        return DocumentTypeDetection(
            document_type=DocumentType.UNKNOWN,
            confidence=top_score.quantize(Decimal("0.01")),
            explanation=_unknown_explanation(top_matches),
        )

    return DocumentTypeDetection(
        document_type=top_type,
        confidence=top_score.quantize(Decimal("0.01")),
        explanation=f"Matched phrases: {', '.join(top_matches)}",
    )


def _score_rule(rule: _DetectionRule, normalized_text: str) -> tuple[Decimal, DocumentType, list[str]]:
    score = Decimal("0.0")
    matches: list[str] = []
    exact_match = False

    for phrase in rule.exact_phrases:
        if phrase.casefold() in normalized_text:
            score += Decimal("0.35")
            matches.append(phrase)
            exact_match = True
            break

    if not exact_match:
        for phrase in rule.weak_phrases:
            if phrase.casefold() in normalized_text:
                score += Decimal("0.25")
                matches.append(phrase)
                break

    keyword_score = Decimal("0.0")
    for keyword in rule.supporting_keywords:
        if keyword.casefold() in normalized_text:
            keyword_score += Decimal("0.1")
            matches.append(keyword)
            if keyword_score >= Decimal("0.55"):
                break

    score += min(keyword_score, Decimal("0.55"))
    return min(score, Decimal("0.95")), rule.document_type, matches


def _unknown_explanation(matches: list[str]) -> str:
    if matches:
        return f"No document type reached confidence 0.45. Matched phrases: {', '.join(matches)}"
    return "No document type reached confidence 0.45. No strong type phrases matched."

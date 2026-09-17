from dataclasses import dataclass
from decimal import Decimal
import re

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
_CURRENT_DEFENSE = re.compile(r"^current(?:\s+(?:defen[cs]e|gate|review))?", re.IGNORECASE)
_PROGRESS_REVIEW = re.compile(r"\b(?:progress|progres\s+s)\s+review\b", re.IGNORECASE)
_STAGE_PATTERNS = (
    (DocumentType.GATE_2, re.compile(r"\bgate\s*[-–]?\s*2\b", re.IGNORECASE)),
    (DocumentType.GATE_3, re.compile(r"\bgate\s*[-–]?\s*3\b", re.IGNORECASE)),
    (
        DocumentType.STREAM_REVIEW_1,
        re.compile(r"\b(?:1st\s+stream\s+review|stream\s+review\s*#?\s*1|sr\s*#?\s*1)\b", re.IGNORECASE),
    ),
    (
        DocumentType.STREAM_REVIEW_2_PLUS,
        re.compile(r"\b(?:2nd\s+stream\s+review|stream\s+review\s*#?\s*(?:2\+|[2-9])|sr\s*#?\s*2\+?)(?!\d)", re.IGNORECASE),
    ),
    (DocumentType.STREAM_REVIEW_2_PLUS, _PROGRESS_REVIEW),
)
_UNSUPPORTED_STAGE_PATTERNS = (
    re.compile(r"\bgate\s*[-–]?\s*1\b", re.IGNORECASE),
)


def detect_document_type(text: str) -> DocumentTypeDetection:
    current_stage = _current_defense_stage(text)
    title_stage = _title_stage(text)
    if current_stage is not None:
        document_type, phrase = current_stage
        explanation = f"Current defense: {phrase}"
        if document_type == DocumentType.UNKNOWN:
            explanation += " (unsupported document type)"
        elif _PROGRESS_REVIEW.fullmatch(phrase):
            explanation += " (using Stream Review 2+ rules)"
        if title_stage is not None and title_stage[0] != document_type:
            explanation += f" (document title says {title_stage[1]})"
        return DocumentTypeDetection(document_type, Decimal("0.95"), explanation)
    if title_stage is not None:
        explanation = f"Document title: {title_stage[1]}"
        if title_stage[0] == DocumentType.UNKNOWN:
            explanation += " (unsupported document type)"
        elif _PROGRESS_REVIEW.fullmatch(title_stage[1]):
            explanation += " (using Stream Review 2+ rules)"
        return DocumentTypeDetection(title_stage[0], Decimal("0.90"), explanation)

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


def progress_review_display_stage(text: str | None, effective_type: str, *, title: str | None = None) -> str | None:
    """Preserve Stream Review 2+ rules while showing an explicit current Progress Review."""
    if not text or effective_type != DocumentType.STREAM_REVIEW_2_PLUS.value:
        return None
    stage = _current_defense_stage(text)
    if stage is None:
        stage = _title_stage(text[:2000])
    if stage is None and title:
        stage = _title_stage(title)
    if stage is not None and stage[1] == "Progress Review":
        return "Progress Review"
    return None


def _current_defense_stage(text: str) -> tuple[DocumentType, str] | None:
    lines = text[:16000].replace("\xa0", " ").splitlines()
    last_summary_index: int | None = None
    for index, raw_line in enumerate(lines):
        line = raw_line.strip().strip("| ").strip()
        if "executive summary" in line.casefold():
            last_summary_index = index
        marker = _CURRENT_DEFENSE.match(line)
        if marker is None:
            continue
        if marker.group().casefold() == "current" and (
            last_summary_index is None or index - last_summary_index > 180
        ):
            continue
        suffix = line[marker.end():].strip(" :|")
        if suffix:
            if marker.group().casefold().endswith("gate") and re.match(r"[123]\b", suffix):
                suffix = f"Gate {suffix}"
            same_line_stage = _explicit_stage(suffix, at_start=True)
            if same_line_stage is not None:
                return same_line_stage
            continue
        following = [
            candidate.strip().strip("| ").strip()
            for candidate in lines[index + 1 : index + 4]
            if candidate.strip() and not candidate.strip().startswith("[Page ")
        ]
        if following:
            stage = _explicit_stage(" ".join(following), at_start=True)
            if stage is not None:
                return stage
    return None


def _title_stage(text: str) -> tuple[DocumentType, str] | None:
    lines = [line.strip() for line in text.replace("\xa0", " ").splitlines() if line.strip()]
    title_lines = [line for line in lines[:4] if not line.startswith("[Page ")]
    if title_lines:
        stage = _explicit_stage(title_lines[0])
        if stage is not None:
            return stage
    if len(title_lines) > 1 and len(title_lines[0]) < 80:
        return _explicit_stage(title_lines[1], at_start=True)
    return None


def _explicit_stage(text: str, *, at_start: bool = False) -> tuple[DocumentType, str] | None:
    matches: list[tuple[DocumentType, str]] = []
    for document_type, pattern in _STAGE_PATTERNS:
        match = pattern.match(text) if at_start else pattern.search(text)
        if match is not None:
            matches.append((document_type, match.group()))
    for pattern in _UNSUPPORTED_STAGE_PATTERNS:
        match = pattern.match(text) if at_start else pattern.search(text)
        if match is not None:
            matches.append((DocumentType.UNKNOWN, match.group()))
    if len({document_type for document_type, _ in matches}) != 1:
        return None
    document_type, phrase = matches[0]
    if _PROGRESS_REVIEW.fullmatch(phrase):
        phrase = "Progress Review"
    return document_type, phrase


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

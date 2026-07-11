import json
import re
from pathlib import Path
from typing import Any

from jsonschema import validate


FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
DEVILS_ADVOCATE_SCHEMA = "devils-advocate-result.schema.json"
SECTION_HEADING_RE = re.compile(r"^\s{0,3}(#{1,2})\s+(.+?)\s*$")
SUBSECTION_HEADING_RE = re.compile(r"^\s{0,3}#{3,6}\s+(.+?)\s*$")
IC_DECISION_RE = re.compile(r"^\s*={3,}\s*(IC Decision)\s*={3,}\s*$", re.IGNORECASE)
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$")
BOLD_LABEL_RE = re.compile(r"^\s*(?:[-*+]\s*)?\*\*(.+?):\*\*\s*(.*?)\s*$")
ANCHOR_COMMENT_RE = re.compile(r'^\s*[*-]\s+(?:\*|_)?["“]?(.+?)["”]?(?:\*|_)?\s*[—-]\s*(.+?)\s*$')


def parse_json_output(structured_text: str) -> Any:
    return _loads_json_output(_extract_json_text(structured_text))


def parse_and_validate_json_output(*, structured_text: str, schema_path: str) -> dict:
    payload = parse_json_output(structured_text)
    schema = json.loads(_resolve_schema_path(schema_path).read_text(encoding="utf-8"))
    payload = _normalize_payload_for_schema(payload=payload, schema=schema, schema_path=schema_path)
    validate(instance=payload, schema=schema)
    return payload


def _loads_json_output(json_text: str) -> Any:
    try:
        return json.loads(json_text)
    except json.JSONDecodeError as exc:
        if "Invalid control character" not in exc.msg:
            raise
        return json.loads(json_text, strict=False)


def _extract_json_text(structured_text: str) -> str:
    stripped = structured_text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped
    match = FENCED_JSON_RE.search(stripped)
    if match:
        return match.group(1).strip()
    return structured_text


def _resolve_schema_path(schema_path: str) -> Path:
    root = Path(__file__).resolve().parents[3]
    return root / schema_path


def _normalize_payload_for_schema(*, payload: Any, schema: dict, schema_path: str) -> Any:
    if not isinstance(payload, dict):
        return payload
    if Path(schema_path).name != DEVILS_ADVOCATE_SCHEMA:
        return payload
    markdown = payload.get("native_markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        return payload
    missing_required = set(schema.get("required", [])) - set(payload)
    if not missing_required:
        return payload
    return _normalize_devils_advocate_markdown_payload(payload=payload, markdown=markdown, schema=schema)


def _normalize_devils_advocate_markdown_payload(*, payload: dict, markdown: str, schema: dict) -> dict:
    allowed_keys = set((schema.get("properties") or {}).keys())
    normalized = {key: value for key, value in payload.items() if key in allowed_keys}
    sections = _markdown_sections(markdown)
    preflight = _section_text(sections, "pre-flight", "preflight")
    brutal_truth = _section_text(sections, "brutal truth")
    contradictions = _section_text(sections, "detected contradictions", "missing proofs")
    role_synthesis = _section_text(sections, "role comments", "voter synthesis")
    tough_questions = _section_text(sections, "tough co-ceo", "tough co ceo")
    actionable_jtbds = _section_text(sections, "actionable jtbd")
    ic_decision = _section_text(sections, "ic decision")

    normalized.setdefault("run_mode", "full_ic_voting")
    normalized.setdefault("preflight_summary", _list_items(preflight))
    normalized.setdefault("brutal_truth", _plain_section_text(brutal_truth))
    normalized.setdefault("detected_contradictions", _detected_contradictions(contradictions))
    normalized.setdefault("role_comments", _role_comments(role_synthesis))
    normalized.setdefault("tough_questions", _tough_questions(tough_questions))
    normalized.setdefault("actionable_jtbds", _list_items(actionable_jtbds, limit=3))
    normalized.setdefault("ic_decision", _ic_decision(ic_decision, normalized.get("role_comments") or []))
    normalized.setdefault("predicted_questions", [item["question"] for item in normalized.get("tough_questions", [])])
    normalized.setdefault("consulted_wiki_pages", [])
    normalized.setdefault("source_citations", [])
    normalized.setdefault("retrieval", {})
    return normalized


def _markdown_sections(markdown: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_lines: list[str] = []
    for line in markdown.splitlines():
        heading = SECTION_HEADING_RE.match(line)
        ic_heading = IC_DECISION_RE.match(line)
        if heading or ic_heading:
            if current_title or current_lines:
                sections.append((current_title, current_lines))
            current_title = (heading.group(2) if heading else ic_heading.group(1)).strip()
            current_lines = []
            continue
        current_lines.append(line)
    if current_title or current_lines:
        sections.append((current_title, current_lines))
    return [(title, "\n".join(lines).strip()) for title, lines in sections]


def _section_text(sections: list[tuple[str, str]], *needles: str) -> str:
    lowered_needles = [needle.lower() for needle in needles]
    for title, body in sections:
        normalized_title = title.lower()
        if any(needle in normalized_title for needle in lowered_needles):
            return body
    return ""


def _plain_section_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()


def _list_items(text: str, *, limit: int | None = None) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        match = LIST_ITEM_RE.match(line)
        if match:
            items.append(match.group(1).strip())
            if limit is not None and len(items) >= limit:
                break
    return items


def _detected_contradictions(text: str) -> list[dict]:
    items: list[dict] = []
    for title, body in _subsections(text):
        if not title and not body:
            continue
        parsed = _bold_labels(body)
        issue_body = _first_label(parsed, "суть", "body", "issue") or _plain_section_text(body)
        item_title = _strip_leading_number(title) or _first_line(issue_body) or "Detected contradiction"
        item_section = _first_label(parsed, "раздел", "section") or item_title
        citations_value = _first_label(parsed, "citations", "citation", "цитаты", "цитата")
        items.append(
            {
                "section": item_section,
                "title": item_title,
                "body": issue_body,
                "comment_type": _comment_type_for_text(f"{item_title}\n{issue_body}"),
                "severity": _normalize_general_severity(_first_label(parsed, "severity", "важность")),
                "citations": _citations(citations_value),
            }
        )
    return items


def _role_comments(text: str) -> list[dict]:
    by_voter: dict[str, dict] = {}
    for title, body in _subsections(text):
        voter = _voter_from_title(title)
        if voter is None:
            continue
        parsed = _bold_labels(body)
        rationale = _first_label(parsed, "рациональное", "rationale") or _first_non_list_line(body)
        by_voter[voter] = {
            "voter": voter,
            "vote": _vote_from_text(title),
            "rationale": rationale or "See native_markdown for rationale.",
            "comments": _anchor_comments(body),
        }
    return [by_voter[voter] for voter in ("MP", "CPO", "TechDir", "VertDir") if voter in by_voter]


def _tough_questions(text: str) -> list[dict]:
    questions: list[dict] = []
    for item in _list_items(text, limit=5):
        persona_match = re.search(r"\[\[persona-[^\]]+\]\]", item)
        persona = persona_match.group(0) if persona_match else "IC"
        question = re.sub(r"^\*\([^)]*\)\*\s*", "", item).strip()
        questions.append({"question": question, "persona": persona})
    return questions


def _ic_decision(text: str, role_comments: list[dict]) -> dict:
    parsed = _bold_labels(text)
    role_votes = {item["voter"]: item["vote"] for item in role_comments if item.get("voter") and item.get("vote")}
    return {
        "verdict": _verdict(_first_label(parsed, "verdict")),
        "vote_tally": _vote_tally(_first_label(parsed, "vote tally"), role_votes),
        "rationale": _first_label(parsed, "rationale") or _first_non_list_line(text) or "See native_markdown.",
        "conditions": _items_after_label(text, "conditions to close before resubmission", "conditions"),
        "heuristics_fired": _items_after_label(text, "heuristics fired"),
        "patterns_fired": _items_after_label(text, "patterns fired"),
        "precedents_anchored": _items_after_label(text, "precedents anchored"),
        "next_ic": _first_label(parsed, "next ic") or "",
    }


def _subsections(text: str) -> list[tuple[str, str]]:
    subsections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_lines: list[str] = []
    for line in text.splitlines():
        heading = SUBSECTION_HEADING_RE.match(line)
        if heading:
            if current_title or current_lines:
                subsections.append((current_title, current_lines))
            current_title = heading.group(1).strip()
            current_lines = []
            continue
        current_lines.append(line)
    if current_title or current_lines:
        subsections.append((current_title, current_lines))
    return [(title, "\n".join(lines).strip()) for title, lines in subsections]


def _bold_labels(text: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    for line in text.splitlines():
        match = BOLD_LABEL_RE.match(line)
        if match:
            labels[_normalize_label(match.group(1))] = match.group(2).strip()
    return labels


def _first_label(labels: dict[str, str], *names: str) -> str:
    for name in names:
        value = labels.get(_normalize_label(name))
        if value:
            return value
    return ""


def _normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip().lower())


def _strip_leading_number(value: str) -> str:
    return re.sub(r"^\s*\d+[.)]\s*", "", value).strip()


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _first_non_list_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not LIST_ITEM_RE.match(stripped) and not BOLD_LABEL_RE.match(stripped):
            return stripped
    return ""


def _comment_type_for_text(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("missing", "proof", "baseline", "отсутств", "не подтверж")):
        return "missing_data"
    if any(token in lowered for token in ("estimate", "forecast", "прогноз", "оценк")):
        return "unrealistic_estimate"
    if any(token in lowered for token in ("method", "методолог")):
        return "methodology_issue"
    if any(token in lowered for token in ("alternative", "альтернатив")):
        return "missing_alternative"
    return "risk_not_addressed"


def _normalize_general_severity(value: str) -> str:
    lowered = value.lower()
    if "critical" in lowered or "крит" in lowered:
        return "critical"
    if "high" in lowered or "важ" in lowered:
        return "high"
    if "medium" in lowered or "сред" in lowered:
        return "medium"
    if "low" in lowered or "minor" in lowered or "низ" in lowered:
        return "low"
    return "high"


def _citations(value: str) -> list[str]:
    if not value:
        return []
    wiki_links = re.findall(r"\[\[[^\]]+\]\]", value)
    if wiki_links:
        return wiki_links
    return [item.strip().strip('"') for item in re.split(r";|,\s+(?=[A-ZА-Я\"'])", value) if item.strip()]


def _voter_from_title(title: str) -> str | None:
    lowered = title.lower()
    if "[mp]" in lowered or "managing partner" in lowered:
        return "MP"
    if "[cpo]" in lowered or re.search(r"\bcpo\b", lowered):
        return "CPO"
    if "[techdir]" in lowered or "technical director" in lowered:
        return "TechDir"
    if "[vertdir]" in lowered or "vertical director" in lowered:
        return "VertDir"
    return None


def _vote_from_text(text: str) -> str:
    lowered = text.lower()
    if "approve" in lowered and "reject" not in lowered:
        return "approve"
    if "за" in lowered and "против" not in lowered:
        return "approve"
    return "reject"


def _anchor_comments(text: str) -> list[dict]:
    comments: list[dict] = []
    for line in text.splitlines():
        match = ANCHOR_COMMENT_RE.match(line)
        if not match:
            continue
        anchor = match.group(1).strip()
        body = match.group(2).strip()
        comments.append(
            {
                "anchor_text": anchor,
                "body": body,
                "comment_type": _comment_type_for_text(f"{anchor}\n{body}"),
                "severity": _role_comment_severity(body),
            }
        )
    return comments


def _role_comment_severity(text: str) -> str:
    lowered = text.lower()
    if "critical" in lowered or "крит" in lowered:
        return "critical"
    if "minor" in lowered or "низ" in lowered:
        return "minor"
    return "important"


def _verdict(value: str) -> str:
    lowered = value.lower()
    if "conditional" in lowered:
        return "conditional_approve"
    if "approve" in lowered and "reject" not in lowered:
        return "approve"
    if "reject" in lowered:
        return "reject"
    if "rework" in lowered or "доработ" in lowered:
        return "rework"
    return "unknown"


def _vote_tally(value: str, role_votes: dict[str, str]) -> dict[str, str]:
    votes = dict(role_votes)
    for voter in ("MP", "CPO", "TechDir", "VertDir"):
        match = re.search(rf"{voter}\s*=\s*(approve|reject)", value, re.IGNORECASE)
        if match:
            votes[voter] = match.group(1).lower()
    return {voter: votes.get(voter, "reject") for voter in ("MP", "CPO", "TechDir", "VertDir")}


def _items_after_label(text: str, *labels: str) -> list[str]:
    normalized_labels = {_normalize_label(label) for label in labels}
    collecting = False
    items: list[str] = []
    for line in text.splitlines():
        label_match = BOLD_LABEL_RE.match(line)
        if label_match:
            label = _normalize_label(label_match.group(1))
            if collecting and label not in normalized_labels:
                break
            collecting = label in normalized_labels
            inline_value = label_match.group(2).strip()
            if collecting and inline_value:
                items.append(inline_value)
            continue
        if collecting:
            item_match = LIST_ITEM_RE.match(line)
            if item_match:
                items.append(item_match.group(1).strip())
            elif line.strip() and items:
                break
    return items

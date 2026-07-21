from typing import Any


SYNTHESIS_VERSION = "devils-advocate-layer-4-synthesis-v1"
SIGNAL_LIMIT = 8

_MUST_REVIEW_SEVERITIES = {"critical", "high", "important"}
_SEVERITY_RANK = {
    "critical": 0,
    "high": 1,
    "important": 2,
    "medium": 3,
    "minor": 4,
    "low": 5,
}


def build_layer_4_synthesis(devils_advocate_output: dict[str, Any]) -> dict[str, Any]:
    ic_decision = _as_dict(devils_advocate_output.get("ic_decision"))
    signals = [
        *_contradiction_signals(devils_advocate_output.get("detected_contradictions")),
        *_role_comment_signals(devils_advocate_output.get("role_comments")),
    ]
    ranked_signals = sorted(signals, key=lambda item: (_severity_rank(item.get("severity")), item.get("theme") or ""))
    must_review_signals = [signal for signal in ranked_signals if signal.get("must_review")][:SIGNAL_LIMIT]

    return {
        "version": SYNTHESIS_VERSION,
        "decision": {
            "verdict": ic_decision.get("verdict") or "unknown",
            "rationale": _compact_text(ic_decision.get("rationale")),
            "vote_tally": ic_decision.get("vote_tally") or {},
            "next_ic": _compact_text(ic_decision.get("next_ic")),
        },
        "must_review_signals": _dedupe_signals(must_review_signals),
        "role_consensus": _role_consensus(devils_advocate_output.get("role_comments")),
        "open_ic_questions": _open_ic_questions(devils_advocate_output.get("tough_questions")),
    }


def format_layer_4_synthesis_markdown(synthesis: dict[str, Any] | None) -> str:
    if not synthesis:
        return ""

    lines = [
        "Layer 4 synthesis - must-review Devil's Advocate signals",
        "Critical/high/important Devil's Advocate signals must not be silently dropped.",
        "If a must-review signal is not included in Layer 1 or Layer 2, explicitly explain why it is not material.",
    ]
    decision = _as_dict(synthesis.get("decision"))
    verdict = decision.get("verdict")
    rationale = decision.get("rationale")
    if verdict or rationale:
        decision_line = f"Decision: {verdict or 'unknown'}"
        if rationale:
            decision_line += f" - {rationale}"
        lines.extend(["", decision_line])

    signals = synthesis.get("must_review_signals") or []
    lines.extend(["", "Must-review signals:"])
    if signals:
        for index, signal in enumerate(signals, start=1):
            lines.append(_format_signal(index=index, signal=_as_dict(signal)))
    else:
        lines.append("- No critical/high/important Devil's Advocate signals were extracted.")

    role_consensus = synthesis.get("role_consensus") or []
    if role_consensus:
        lines.extend(["", "Role consensus:"])
        lines.extend(f"- {item}" for item in role_consensus)

    questions = synthesis.get("open_ic_questions") or []
    if questions:
        lines.extend(["", "Open IC questions:"])
        lines.extend(f"- {question}" for question in questions)

    return "\n".join(lines)


def _contradiction_signals(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []

    signals = []
    for item in items:
        if not isinstance(item, dict):
            continue
        severity = _compact_text(item.get("severity")).lower()
        signals.append(
            {
                "source": "detected_contradiction",
                "theme": _compact_text(item.get("title") or item.get("section") or item.get("comment_type")),
                "severity": severity or "medium",
                "evidence": _join_values(item.get("citations")),
                "why_it_matters": _compact_text(item.get("body")),
                "comment_type": _compact_text(item.get("comment_type")),
                "must_review": severity in _MUST_REVIEW_SEVERITIES,
            }
        )
    return signals


def _role_comment_signals(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []

    signals = []
    for role_item in items:
        if not isinstance(role_item, dict):
            continue
        voter = _compact_text(role_item.get("voter"))
        vote = _compact_text(role_item.get("vote"))
        comments = role_item.get("comments") or []
        if not isinstance(comments, list):
            continue
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            severity = _compact_text(comment.get("severity")).lower()
            anchor = _compact_text(comment.get("anchor_text"))
            comment_type = _compact_text(comment.get("comment_type"))
            signals.append(
                {
                    "source": "role_comment",
                    "theme": anchor or _humanize(comment_type) or voter or "Role comment",
                    "severity": severity or "minor",
                    "evidence": anchor,
                    "why_it_matters": _compact_text(comment.get("body")),
                    "comment_type": comment_type,
                    "persona": voter,
                    "vote": vote,
                    "must_review": severity in _MUST_REVIEW_SEVERITIES,
                }
            )
    return signals


def _role_consensus(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []

    consensus = []
    for item in items:
        if not isinstance(item, dict):
            continue
        voter = _compact_text(item.get("voter"))
        vote = _compact_text(item.get("vote"))
        rationale = _compact_text(item.get("rationale"))
        if not voter or not rationale:
            continue
        vote_label = "rejects" if vote == "reject" else "approves" if vote == "approve" else vote or "votes"
        consensus.append(f"{voter} {vote_label}: {rationale}")
    return consensus[:4]


def _open_ic_questions(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    questions = []
    for item in items:
        if isinstance(item, dict):
            question = _compact_text(item.get("question"))
        else:
            question = _compact_text(item)
        if question:
            questions.append(question)
    return questions[:5]


def _dedupe_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen = set()
    for signal in signals:
        key = (signal.get("source"), signal.get("theme"), signal.get("why_it_matters"))
        if key in seen:
            continue
        deduped.append(signal)
        seen.add(key)
    return deduped


def _format_signal(*, index: int, signal: dict[str, Any]) -> str:
    severity = signal.get("severity") or "unknown"
    theme = signal.get("theme") or f"Signal {index}"
    source = signal.get("source") or "unknown"
    parts = [f"{index}. [{severity}] {theme} ({source})"]
    persona = signal.get("persona")
    if persona:
        parts.append(f"Persona: {persona}.")
    evidence = signal.get("evidence")
    if evidence:
        parts.append(f"Evidence: {evidence}.")
    why_it_matters = signal.get("why_it_matters")
    if why_it_matters:
        parts.append(f"Why it matters: {why_it_matters}")
    return " ".join(parts)


def _severity_rank(severity: Any) -> int:
    return _SEVERITY_RANK.get(_compact_text(severity).lower(), 99)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _compact_text(value: Any, *, limit: int = 600) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _join_values(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(_compact_text(item, limit=180) for item in value if _compact_text(item, limit=180))
    return _compact_text(value)


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip().title()

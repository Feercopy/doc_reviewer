import json
from typing import Any

from skills.layer_4_synthesis import format_layer_4_synthesis_markdown
from skills.output_language import normalize_output_language, output_language_instruction
from skills.snapshot_loader import SkillSourceSnapshotMaterial

_COMMON_REFERENCE_FILES = {
    "common-adversarial-rubric.md",
    "common-output-contract.md",
    "common-synthesis-contract.md",
    "common-verdict-policy.md",
    "stage-detection.md",
}
_STAGE_REFERENCE_FILES = {
    "gate_2": "gate-2-rubric.md",
    "stream_review_1": "stream-review-1-rubric.md",
    "stream_review_2_plus": "stream-review-2-plus-rubric.md",
    "gate_3": "gate-3-rubric.md",
}
_KNOWN_STAGE_REFERENCE_FILES = set(_STAGE_REFERENCE_FILES.values())


def render_gate2_challenger_prompt(
    *,
    document: Any,
    skill: Any,
    response_schema: dict,
    source_snapshot: SkillSourceSnapshotMaterial | None = None,
    output_language: str | None = None,
    layer_4_context: dict | None = None,
) -> str:
    document_type = getattr(document, "manual_document_type", None) or getattr(document, "detected_document_type", "unknown")
    skill_prompt = _skill_prompt_text(skill=skill, source_snapshot=source_snapshot)
    reference_context = _reference_context(source_snapshot, document_type=document_type)
    normalized_output_language = normalize_output_language(output_language)
    layer_4_context_text = _layer_4_context_text(layer_4_context)
    source_lines = [
        "Gate2-challenger source snapshot:",
        f"- source_uri: {_source_value(skill, source_snapshot, 'source_slug')}",
        f"- source_entrypoint: {getattr(skill, 'source_entrypoint', None) or 'inline'}",
        f"- source_revision: {_source_value(skill, source_snapshot, 'resolved_revision')}",
        f"- source_fingerprint: {_source_value(skill, source_snapshot, 'source_fingerprint')}",
    ]
    parts = [
        f"Skill: {skill.name} ({skill.version})",
        "\n".join(source_lines),
        "Use the canonical Gate2-challenger review method. Preserve the six-pass review intent, "
        "including coordinator normalization, stage detection and routing, Layer 1 decision-critical review, "
        "Layer 2 atomic weak-link review, adversarial committee-risk review, and final synthesis.",
        output_language_instruction(output_language) if output_language is not None else "",
        "External skill instructions:",
        skill_prompt,
        "External skill references:",
        reference_context,
    ]
    if layer_4_context_text:
        parts.extend(
            [
                "Layer 4 expert analysis context:",
                layer_4_context_text,
            ]
        )
    parts.extend(
        [
            "Mandatory output format:",
            _output_requirements(response_schema=response_schema, output_language=normalized_output_language),
            f"Document title: {document.title}",
            f"Document type: {document_type}",
            "Return only JSON matching this schema:",
            json.dumps(response_schema, ensure_ascii=False, sort_keys=True),
            "Parsed document text:",
            document.parsed_text or "",
        ]
    )
    return "\n\n".join(parts)


def _output_requirements(*, response_schema: dict, output_language: str) -> str:
    title = response_schema.get("title")
    if title == "MainAnalysisSummaryResult":
        return "\n".join(
            [
                "Return JSON only, but the first visible reader-facing answer must be compact.",
                _assessment_markdown_requirement(output_language),
                "2. layer_1_index: compact evidence-backed index of decision-critical Layer 1 issues. "
                "Each item must include id, severity, issue, and evidence_anchor only.",
                "Before finalizing layer_1_index, apply the external skill's root-cause registry and atomization pass: "
                "place each issue in its primary dimension-home, repeat it only for distinct local decision consequences, "
                "and split only independent committee decision problems.",
                "3. layer_2_index: compact index of atomic Layer 2 checks with id, parent_layer_1_id, "
                "status, severity, question, answer, and short_evidence only.",
                "Before finalizing layer_2_index, verify that every atomic question from the selected stage rubric is "
                "represented exactly once, with unchanged question text and exactly one answer, evidence, and issue.",
                "4. details_status must be exactly not_requested, details_run_id must be null, "
                "revision_required must be false, and revision_reason must be null.",
                "Do the full Gate Challenger reasoning now, but do not output full detailed check blocks in this response.",
                "Use Layer 4 expert analysis to strengthen or supplement Gate Challenger findings when it adds "
                "document-grounded issues or reinforces problems you independently find.",
            ]
        )

    return "\n".join(
        [
            "Return JSON only, but the visible reader-facing answer must be encoded in these required fields:",
            _assessment_markdown_requirement(output_language),
            "2. layer_1_markdown: reader-facing Layer 1 block after the summary, in strict Gate Challenger format. "
            "Each Layer 1 item must expose only issue, evidence, and severity; do not add Title, Impact, or Recommendation subblocks.",
            "Before finalizing Layer 1, apply the external skill's root-cause registry and atomization pass: "
            "place each issue in its primary dimension-home, repeat it only for distinct local decision consequences, "
            "and split only independent committee decision problems.",
            "3. layer_1: structured copy of every Layer 1 item with id, severity, issue, evidence.",
            "4. layer_2_markdown: reader-facing Layer 2 block after Layer 1, in strict Gate Challenger format.",
            "5. layer_2: structured copy of every Layer 2 atomic check with id, parent_layer_1_id, status, "
            "severity, question, answer, evidence, issue. Layer 2 item must not include Risk or Recommendation fields.",
            "Before returning Layer 2, verify exact one-to-one equality with the selected stage rubric's atomic checks: "
            "same block boundaries, block order, question order, question text, and exactly one answer, evidence, and issue per question.",
            "Use Layer 4 expert analysis to strengthen or supplement Gate Challenger findings when it adds "
            "document-grounded issues or reinforces problems you independently find.",
            "Do not collapse Layer 1/Layer 2 into generic findings. The display order is always: "
            "assessment_markdown, then layer_1_markdown, then layer_2_markdown.",
        ]
    )


def _assessment_markdown_requirement(output_language: str) -> str:
    if output_language == "en":
        base_requirement = (
            "1. assessment_markdown: full English summary block starting exactly with 'Document assessment'. "
            "Use the TRX-SE style: recommendation, context, why the decision is this, evidence bullets, "
            "IC recommendation, what can/cannot be approved, improvements, and final conclusion."
        )
        return "\n".join([base_requirement, _assessment_markdown_tone_requirement()])

    base_requirement = (
        "1. assessment_markdown: full Russian summary block starting exactly with 'Оценка документа'. "
        "Use the TRX-SE style: recommendation, context, why the decision is this, evidence bullets, "
        "IC recommendation, what can/cannot be approved, improvements, and final итог."
    )
    return "\n".join([base_requirement, _assessment_markdown_tone_requirement()])


def _assessment_markdown_tone_requirement() -> str:
    return "\n".join(
        [
            "Tone-of-voice for assessment_markdown only:",
            "- Write in CEO/CPO IC language: direct, decision-first, focused on business trade-off.",
            "- Do not change facts, verdicts, evidence, promoted issues, required fields, or required sections.",
            "- After the required exact start, add a short Brutal Truth-style opening: 1-3 sharp sentences "
            "about the core trade-off and why the document is unsafe to approve as written.",
            "- Prefer the frame: what is proven / what is not proven / what cannot be approved yet.",
            "- Explain issues through decision consequences, not rubric labels.",
            "- Avoid opaque methodology terms unless translated into concrete business meaning.",
            "- Do not change Layer 1 / Layer 2 markdown requirements.",
        ]
    )


def _layer_4_context_text(layer_4_context: dict | None) -> str | None:
    if not layer_4_context:
        return None
    markdown = layer_4_context.get("markdown")
    if markdown:
        synthesis_markdown = format_layer_4_synthesis_markdown(layer_4_context.get("synthesis"))
        if synthesis_markdown and "Layer 4 synthesis - must-review Devil's Advocate signals" not in str(markdown):
            return f"{markdown}\n\n3. Structured synthesis contract\n{synthesis_markdown}"
        return str(markdown)

    brutal_truth = layer_4_context.get("brutal_truth") or "No brutal truth block was captured."
    contradictions = layer_4_context.get("detected_contradictions") or []
    lines = [
        "Layer 4 - Devil's Advocate expert analysis",
        "These are results of expert analysis produced before Gate Challenger. Use them to strengthen or "
        "supplement Gate Challenger: add additional document-grounded findings when Devil's Advocate found "
        "something extra, or reinforce the position of problems Gate Challenger also finds. Do not treat "
        "unsupported expert claims as document evidence.",
        "",
        "1. The Brutal Truth",
        str(brutal_truth),
        "",
        "2. Detected Contradictions & Missing Proofs",
    ]
    if contradictions:
        lines.extend(_contradiction_lines(contradictions))
    else:
        lines.append("No detected contradictions or missing proofs were captured.")
    synthesis_markdown = format_layer_4_synthesis_markdown(layer_4_context.get("synthesis"))
    if synthesis_markdown:
        lines.extend(["", "3. Structured synthesis contract", synthesis_markdown])
    return "\n".join(lines)


def _contradiction_lines(contradictions: Any) -> list[str]:
    if not isinstance(contradictions, list):
        return [json.dumps(contradictions, ensure_ascii=False, sort_keys=True)]

    lines = []
    for index, item in enumerate(contradictions, start=1):
        if isinstance(item, dict):
            title = item.get("title") or item.get("section") or f"Item {index}"
            body = item.get("body") or item.get("issue") or item.get("comment") or ""
            severity = item.get("severity")
            citations = item.get("citations") or []
            line = f"{index}. {title}"
            if severity:
                line += f" [{severity}]"
            if body:
                line += f": {body}"
            if citations:
                line += f" Citations: {', '.join(str(citation) for citation in citations)}"
            lines.append(line)
        else:
            lines.append(f"{index}. {item}")
    return lines


def _skill_prompt_text(*, skill: Any, source_snapshot: SkillSourceSnapshotMaterial | None) -> str:
    if source_snapshot is None:
        return skill.prompt_text
    entrypoint = getattr(skill, "source_entrypoint", None)
    if entrypoint and source_snapshot.read_text(entrypoint):
        return source_snapshot.read_text(entrypoint) or ""
    for relative_path, text in sorted(source_snapshot.files.items()):
        if relative_path.endswith("/SKILL.md") or relative_path == "SKILL.md":
            return text
    return "\n\n".join(source_snapshot.files[path] for path in sorted(source_snapshot.files))


def _reference_context(source_snapshot: SkillSourceSnapshotMaterial | None, *, document_type: str | None) -> str:
    if source_snapshot is None:
        return "No snapshot references were attached."
    sections = []
    for relative_path, text in sorted(source_snapshot.files.items()):
        if relative_path.endswith("/SKILL.md") or relative_path == "SKILL.md":
            continue
        if not _should_include_reference(relative_path=relative_path, document_type=document_type):
            continue
        sections.append(f"# {relative_path}\n{text}")
    return "\n\n".join(sections) if sections else "No snapshot references were attached."


def _should_include_reference(*, relative_path: str, document_type: str | None) -> bool:
    filename = relative_path.rsplit("/", 1)[-1]
    expected_stage_file = _STAGE_REFERENCE_FILES.get(str(document_type or ""))

    if filename in _COMMON_REFERENCE_FILES:
        return True
    if expected_stage_file and filename in _KNOWN_STAGE_REFERENCE_FILES:
        return filename == expected_stage_file
    if filename in _KNOWN_STAGE_REFERENCE_FILES:
        return False
    return True


def _source_value(skill: Any, source_snapshot: SkillSourceSnapshotMaterial | None, key: str) -> str:
    if source_snapshot is not None:
        value = source_snapshot.manifest.get(key)
        if value:
            return str(value)
    if key == "resolved_revision":
        return getattr(skill, "source_revision", None) or "unknown"
    if key == "source_fingerprint":
        return getattr(skill, "source_fingerprint", None) or "unknown"
    return getattr(skill, "source_uri", None) or "inline"

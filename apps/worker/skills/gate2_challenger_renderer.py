import json
from typing import Any

from skills.output_language import normalize_output_language, output_language_instruction
from skills.snapshot_loader import SkillSourceSnapshotMaterial


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
    reference_context = _reference_context(source_snapshot)
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
        "Use the canonical Gate2-challenger review method. Preserve the five-pass review intent, "
        "including coordinator normalization, Layer 1 decision-critical review, Layer 2 atomic weak-link "
        "review, adversarial committee-risk review, and final synthesis.",
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
            "\n".join(
                [
                    "Return JSON only, but the visible reader-facing answer must be encoded in these required fields:",
                    _assessment_markdown_requirement(normalized_output_language),
                    "2. layer_1_markdown: reader-facing Layer 1 block after the summary, in strict Gate Challenger format. "
                    "Each Layer 1 item must expose only issue, evidence, and severity; do not add Title, Impact, or Recommendation subblocks.",
                    "3. layer_1: structured copy of every Layer 1 item with id, severity, issue, evidence.",
                    "4. layer_2_markdown: reader-facing Layer 2 block after Layer 1, in strict Gate Challenger format.",
                    "5. layer_2: structured copy of every Layer 2 atomic weak-link item with parent_layer_1_id.",
                    "Use Layer 4 expert analysis to strengthen or supplement Gate Challenger findings when it adds "
                    "document-grounded issues or reinforces problems you independently find.",
                    "Do not collapse Layer 1/Layer 2 into generic findings. The display order is always: "
                    "assessment_markdown, then layer_1_markdown, then layer_2_markdown.",
                ]
            ),
            f"Document title: {document.title}",
            f"Document type: {document_type}",
            "Return only JSON matching this schema:",
            json.dumps(response_schema, ensure_ascii=False, sort_keys=True),
            "Parsed document text:",
            document.parsed_text or "",
        ]
    )
    return "\n\n".join(parts)


def _assessment_markdown_requirement(output_language: str) -> str:
    if output_language == "en":
        return (
            "1. assessment_markdown: full English summary block starting exactly with 'Document assessment'. "
            "Use the TRX-SE style: recommendation, context, why the decision is this, evidence bullets, "
            "IC recommendation, what can/cannot be approved, improvements, and final conclusion."
        )

    return (
        "1. assessment_markdown: full Russian summary block starting exactly with 'Оценка документа'. "
        "Use the TRX-SE style: recommendation, context, why the decision is this, evidence bullets, "
        "IC recommendation, what can/cannot be approved, improvements, and final итог."
    )


def _layer_4_context_text(layer_4_context: dict | None) -> str | None:
    if not layer_4_context:
        return None
    markdown = layer_4_context.get("markdown")
    if markdown:
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


def _reference_context(source_snapshot: SkillSourceSnapshotMaterial | None) -> str:
    if source_snapshot is None:
        return "No snapshot references were attached."
    sections = []
    for relative_path, text in sorted(source_snapshot.files.items()):
        if relative_path.endswith("/SKILL.md") or relative_path == "SKILL.md":
            continue
        sections.append(f"# {relative_path}\n{text}")
    return "\n\n".join(sections) if sections else "No snapshot references were attached."


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

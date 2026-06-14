import json
from pathlib import Path
from typing import Any

from skills.output_language import output_language_instruction
from skills.snapshot_loader import RetrievalSnapshotMaterial, SkillSourceSnapshotMaterial


def render_devils_advocate_prompt(
    *,
    document: Any,
    analysis: Any,
    skill: Any,
    response_schema: dict,
    source_snapshot: SkillSourceSnapshotMaterial | None = None,
    retrieval_snapshot: RetrievalSnapshotMaterial | None = None,
    output_language: str | None = None,
) -> str:
    source_text = _read_source_text(skill, source_snapshot=source_snapshot)
    wiki_sections = _read_selected_wiki_sections(
        skill,
        source_snapshot=source_snapshot,
        retrieval_snapshot=retrieval_snapshot,
    )
    main_output = getattr(analysis, "structured_output", None) or {}
    main_context = {
        "verdict": getattr(analysis, "verdict", None),
        "summary": getattr(analysis, "summary", None),
        "findings": main_output.get("findings", []),
        "checks": main_output.get("checks", []),
        "layer_1": main_output.get("layer_1", []),
        "layer_2": main_output.get("layer_2", []),
        "key_findings": main_output.get("key_findings", []),
        "recommendations": main_output.get("recommendations", []),
    }
    has_main_context = any(
        [
            main_context["verdict"],
            main_context["summary"],
            main_context["findings"],
            main_context["checks"],
            main_context["layer_1"],
            main_context["layer_2"],
            main_context["key_findings"],
            main_context["recommendations"],
        ]
    )
    document_type = getattr(document, "manual_document_type", None) or getattr(document, "detected_document_type", "unknown")

    return "\n\n".join(
        [
            f"Skill: {skill.name} ({skill.version})",
            "Run mode: full_ic_voting",
            _run_mode_instruction(has_main_context),
            output_language_instruction(output_language) if output_language is not None else "",
            "Devil's Advocate source snapshot:",
            "\n".join(_source_lines(skill=skill, source_snapshot=source_snapshot)),
            "External orchestration prompt:",
            source_text,
            "Retrieval dossier:",
            _retrieval_dossier_text(retrieval_snapshot),
            "Expanded retrieval evidence packet:",
            _retrieval_evidence_packet_text(retrieval_snapshot),
            "Selected knowledge base context:",
            "\n\n".join(wiki_sections) if wiki_sections else "No selected wiki pages were available.",
            _main_context_heading(has_main_context),
            json.dumps(main_context if has_main_context else _empty_main_context(), ensure_ascii=False, sort_keys=True),
            "Mandatory native IC voting output format:",
            "\n".join(
                [
                    "Return JSON only, but encode the exact visible Devil's Advocate answer in native_markdown.",
                    "native_markdown must be written in the requested output language.",
                    "native_markdown must follow ic-voting-prompt.md / wiki-ic/meta/output-format.md order:",
                    "1. Title line: 🔴 Devil's Advocate — <IC/stage/domain/document>",
                    "2. Pre-flight summary",
                    "3. The Brutal Truth",
                    "4. Detected Contradictions & Missing Proofs",
                    "5. Role comments / voter synthesis for MP, CPO, TechDir, VertDir using role_comments",
                    "6. The \"Tough Co-CEO\" Questions",
                    "7. Actionable JTBDs",
                    "8. === IC Decision === block with vote tally, rationale, conditions, heuristics, patterns, precedents, next IC.",
                    "role_comments must preserve the original ic-voting-prompt.md subagent contract:",
                    "role_comments[].comments[] must contain exactly anchor_text, body, comment_type, severity.",
                    "anchor_text must be an exact verbatim substring from the input document when possible.",
                    "body must be clean IC-comment prose, no wiki links, no anonym slugs, no persona labels.",
                    "severity for role comments must be one of critical, important, minor.",
                    "Do not use anchor/comment aliases for role_comments[].comments[]; use anchor_text/body.",
                    "The required JSON fields must mirror native_markdown: preflight_summary, brutal_truth, "
                    "detected_contradictions, role_comments, tough_questions, actionable_jtbds, ic_decision, retrieval.",
                    "Do not return the old compact anchored_comments/trailer-only shape as the primary answer.",
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


def _run_mode_instruction(has_main_context: bool) -> str:
    if has_main_context:
        return (
            "Use the Devil's Advocate / IC voting orchestration to predict defense committee comments. "
            "Anchor comments to document evidence and the completed main analysis. Do not invent source citations."
        )
    return (
        "Use the Devil's Advocate / IC voting orchestration as the first expert critique before Gate Challenger. "
        "Anchor comments to document evidence and produce expert issues that can later strengthen or supplement "
        "Gate Challenger. Do not invent source citations."
    )


def _main_context_heading(has_main_context: bool) -> str:
    if has_main_context:
        return "Completed main analysis context:"
    return "Gate Challenger context:"


def _empty_main_context() -> dict:
    return {
        "status": "not_available",
        "reason": "Devil's Advocate runs before Gate Challenger in this workflow.",
    }


def _read_source_text(skill: Any, *, source_snapshot: SkillSourceSnapshotMaterial | None) -> str:
    if source_snapshot is not None:
        entrypoint = getattr(skill, "source_entrypoint", None)
        if entrypoint and source_snapshot.read_text(entrypoint):
            return source_snapshot.read_text(entrypoint) or ""
        if source_snapshot.read_text("ic-voting-prompt.md"):
            return source_snapshot.read_text("ic-voting-prompt.md") or ""
    source_uri = getattr(skill, "source_uri", None)
    if source_uri:
        path = Path(source_uri)
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    return skill.prompt_text


def _read_selected_wiki_sections(
    skill: Any,
    *,
    source_snapshot: SkillSourceSnapshotMaterial | None,
    retrieval_snapshot: RetrievalSnapshotMaterial | None,
) -> list[str]:
    if source_snapshot is not None:
        paths = [
            "wiki-ic/schema.md",
            "wiki-ic/meta/output-format.md",
        ]
        sections = []
        seen: set[str] = set()
        for relative_path in paths:
            if relative_path in seen:
                continue
            seen.add(relative_path)
            text = source_snapshot.read_text(relative_path)
            if text is not None:
                sections.append(f"# {relative_path}\n{text}")
        return sections

    metadata = getattr(skill, "source_metadata", None) or {}
    wiki_path_value = metadata.get("wiki_path")
    if not wiki_path_value:
        return []

    wiki_path = Path(wiki_path_value)
    if not wiki_path.exists() or not wiki_path.is_dir():
        return []

    candidates = [
        wiki_path / "schema.md",
        wiki_path / "meta" / "output-format.md",
    ]
    selected_pages = metadata.get("selected_wiki_pages") or []
    for page in selected_pages:
        page_path = wiki_path / page
        if page_path.exists() and page_path.is_file():
            candidates.append(page_path)

    sections = []
    for path in candidates:
        if path.exists() and path.is_file():
            sections.append(f"# {path.relative_to(wiki_path)}\n{path.read_text(encoding='utf-8')}")
    return sections


def _source_lines(skill: Any, *, source_snapshot: SkillSourceSnapshotMaterial | None) -> list[str]:
    if source_snapshot is None:
        return [
            f"- source_uri: {getattr(skill, 'source_uri', None) or 'inline'}",
            f"- source_entrypoint: {getattr(skill, 'source_entrypoint', None) or 'inline'}",
            f"- source_revision: {getattr(skill, 'source_revision', None) or 'unknown'}",
            f"- source_fingerprint: {getattr(skill, 'source_fingerprint', None) or 'unknown'}",
        ]
    return [
        f"- source_uri: {source_snapshot.manifest.get('source_slug', 'snapshot')}",
        f"- source_entrypoint: {getattr(skill, 'source_entrypoint', None) or 'ic-voting-prompt.md'}",
        f"- source_revision: {source_snapshot.manifest.get('resolved_revision') or 'unknown'}",
        f"- source_fingerprint: {source_snapshot.manifest.get('source_fingerprint') or 'unknown'}",
    ]


def _retrieval_dossier_text(retrieval_snapshot: RetrievalSnapshotMaterial | None) -> str:
    if retrieval_snapshot is None:
        return "No retrieval dossier was attached."
    return json.dumps(retrieval_snapshot.dossier, ensure_ascii=False, sort_keys=True)


def _retrieval_evidence_packet_text(retrieval_snapshot: RetrievalSnapshotMaterial | None) -> str:
    if retrieval_snapshot is None:
        return "No expanded evidence packet was attached."
    evidence_packet = retrieval_snapshot.dossier.get("evidence_packet") or {}
    markdown = evidence_packet.get("markdown")
    if markdown:
        return str(markdown)

    sections = evidence_packet.get("sections") or []
    rendered_sections = []
    for section in sections:
        path = section.get("path") or "unknown"
        content = section.get("content") or ""
        if content:
            rendered_sections.append(f"# {path}\n{content}")
    return "\n\n".join(rendered_sections) if rendered_sections else "No expanded evidence packet was attached."

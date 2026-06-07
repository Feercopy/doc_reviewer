import json
from pathlib import Path
from typing import Any


def render_devils_advocate_prompt(*, document: Any, analysis: Any, skill: Any, response_schema: dict) -> str:
    source_text = _read_source_text(skill)
    wiki_sections = _read_selected_wiki_sections(skill)
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
    document_type = getattr(document, "manual_document_type", None) or getattr(document, "detected_document_type", "unknown")

    return "\n\n".join(
        [
            f"Skill: {skill.name} ({skill.version})",
            "Run mode: full_ic_voting",
            "Use the Devil's Advocate / IC voting orchestration to predict defense committee comments. "
            "Anchor comments to document evidence and the completed main analysis. Do not invent source citations.",
            "Devil's Advocate source snapshot:",
            "\n".join(
                [
                    f"- source_uri: {getattr(skill, 'source_uri', None) or 'inline'}",
                    f"- source_entrypoint: {getattr(skill, 'source_entrypoint', None) or 'inline'}",
                    f"- source_revision: {getattr(skill, 'source_revision', None) or 'unknown'}",
                    f"- source_fingerprint: {getattr(skill, 'source_fingerprint', None) or 'unknown'}",
                ]
            ),
            "External orchestration prompt:",
            source_text,
            "Selected knowledge base context:",
            "\n\n".join(wiki_sections) if wiki_sections else "No selected wiki pages were available.",
            "Completed main analysis context:",
            json.dumps(main_context, ensure_ascii=False, sort_keys=True),
            f"Document title: {document.title}",
            f"Document type: {document_type}",
            "Return only JSON matching this schema:",
            json.dumps(response_schema, ensure_ascii=False, sort_keys=True),
            "Parsed document text:",
            document.parsed_text or "",
        ]
    )


def _read_source_text(skill: Any) -> str:
    source_uri = getattr(skill, "source_uri", None)
    if source_uri:
        path = Path(source_uri)
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    return skill.prompt_text


def _read_selected_wiki_sections(skill: Any) -> list[str]:
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

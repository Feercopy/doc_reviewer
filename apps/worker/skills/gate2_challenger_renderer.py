import json
from typing import Any


def render_gate2_challenger_prompt(*, document: Any, skill: Any, response_schema: dict) -> str:
    document_type = getattr(document, "manual_document_type", None) or getattr(document, "detected_document_type", "unknown")
    source_lines = [
        "Gate2-challenger source snapshot:",
        f"- source_uri: {getattr(skill, 'source_uri', None) or 'inline'}",
        f"- source_entrypoint: {getattr(skill, 'source_entrypoint', None) or 'inline'}",
        f"- source_revision: {getattr(skill, 'source_revision', None) or 'unknown'}",
        f"- source_fingerprint: {getattr(skill, 'source_fingerprint', None) or 'unknown'}",
    ]
    return "\n\n".join(
        [
            f"Skill: {skill.name} ({skill.version})",
            "\n".join(source_lines),
            "Use the canonical Gate2-challenger review method. Preserve the five-pass review intent, "
            "including coordinator normalization, Layer 1 decision-critical review, Layer 2 atomic weak-link "
            "review, adversarial committee-risk review, and final synthesis.",
            "External skill instructions:",
            skill.prompt_text,
            f"Document title: {document.title}",
            f"Document type: {document_type}",
            "Return only JSON matching this schema:",
            json.dumps(response_schema, ensure_ascii=False, sort_keys=True),
            "Parsed document text:",
            document.parsed_text or "",
        ]
    )

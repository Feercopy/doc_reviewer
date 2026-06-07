from app.models.document import Document
from app.models.skill import Skill
from skills.gate2_challenger_renderer import render_gate2_challenger_prompt


def render_prompt(*, document: Document, skill: Skill, response_schema: dict) -> str:
    if skill.name == "gate2_challenger_main_analysis":
        return render_gate2_challenger_prompt(document=document, skill=skill, response_schema=response_schema)

    return "\n\n".join(
        [
            f"Skill: {skill.name} ({skill.version})",
            f"Document title: {document.title}",
            f"Document type: {document.manual_document_type or document.detected_document_type}",
            "Return only JSON matching this schema:",
            str(response_schema),
            "Parsed document text:",
            document.parsed_text or "",
        ]
    )

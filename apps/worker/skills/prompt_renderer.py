from app.models.document import Document
from app.models.skill import Skill
from skills.gate2_challenger_renderer import render_gate2_challenger_prompt
from skills.snapshot_loader import load_skill_source_snapshot


def render_prompt(*, document: Document, skill: Skill, response_schema: dict, run_parameters: dict | None = None) -> str:
    if skill.name == "gate2_challenger_main_analysis":
        source_snapshot = _load_snapshot_for_skill(skill=skill, run_parameters=run_parameters or {})
        return render_gate2_challenger_prompt(
            document=document,
            skill=skill,
            response_schema=response_schema,
            source_snapshot=source_snapshot,
        )

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


def _load_snapshot_for_skill(*, skill: Skill, run_parameters: dict):
    artifact_path = run_parameters.get("source_snapshot_artifact_path")
    snapshot = run_parameters.get("skill_source_snapshot") or {}
    artifact_path = artifact_path or snapshot.get("artifact_path")
    requires_snapshot = bool(getattr(skill, "skill_source_id", None)) and getattr(skill, "runtime_mode", None) == "snapshot_required"
    if not artifact_path:
        if requires_snapshot:
            raise RuntimeError("source_snapshot_required")
        return None
    return load_skill_source_snapshot(str(artifact_path))

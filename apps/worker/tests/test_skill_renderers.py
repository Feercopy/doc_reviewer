from types import SimpleNamespace

from skills.devils_advocate_renderer import render_devils_advocate_prompt
from skills.gate2_challenger_renderer import render_gate2_challenger_prompt


def test_gate2_challenger_renderer_frames_external_skill_with_schema_and_document():
    document = SimpleNamespace(
        title="Gate 2 defense",
        parsed_text="The initiative claims strong MVP traction but omits cohort evidence.",
        manual_document_type=None,
        detected_document_type="gate_2",
    )
    skill = SimpleNamespace(
        name="gate2_challenger_main_analysis",
        version="baseline",
        prompt_text="Run a five-pass Gate 2 review with Layer 1 and Layer 2 findings.",
        source_uri="/Users/example/Gate2/skills/gate2-challenger/SKILL.md",
        source_entrypoint="SKILL.md",
        source_revision="abc123",
        source_fingerprint="fingerprint",
    )

    prompt = render_gate2_challenger_prompt(
        document=document,
        skill=skill,
        response_schema={"title": "MainAnalysisResult", "type": "object"},
    )

    assert "Gate2-challenger source snapshot" in prompt
    assert "five-pass Gate 2 review" in prompt
    assert "Layer 1" in prompt
    assert "Layer 2" in prompt
    assert "Return only JSON matching this schema" in prompt
    assert "MainAnalysisResult" in prompt
    assert "The initiative claims strong MVP traction" in prompt


def test_devils_advocate_renderer_includes_main_result_and_selected_knowledge_base(tmp_path):
    knowledge_base = tmp_path / "wiki-ic"
    meta_dir = knowledge_base / "meta"
    meta_dir.mkdir(parents=True)
    (tmp_path / "ic-voting-prompt.md").write_text("IC voting orchestrator", encoding="utf-8")
    (knowledge_base / "schema.md").write_text("Wiki schema contract", encoding="utf-8")
    (meta_dir / "output-format.md").write_text("Four-section trailer format", encoding="utf-8")
    (knowledge_base / "risk-patterns.md").write_text("Known red-flag patterns", encoding="utf-8")

    document = SimpleNamespace(
        title="Gate 2 defense",
        parsed_text="The document asks for investment approval without incrementality proof.",
        manual_document_type=None,
        detected_document_type="gate_2",
    )
    skill = SimpleNamespace(
        name="devils_advocate_predefense",
        version="baseline",
        prompt_text="Fallback DA prompt",
        source_uri=str(tmp_path / "ic-voting-prompt.md"),
        source_entrypoint="ic-voting-prompt.md",
        source_revision="def456",
        source_fingerprint="da-fingerprint",
        source_metadata={"wiki_path": str(knowledge_base), "selected_wiki_pages": ["risk-patterns.md"]},
    )
    analysis = SimpleNamespace(
        verdict="need_evidence",
        summary="Needs incrementality evidence.",
        structured_output={
            "findings": [{"id": "F1", "title": "Missing incrementality proof"}],
            "checks": [{"name": "Control group", "explanation": "No holdout"}],
            "layer_1": [{"id": "L1-1", "summary": "Traction evidence is weak"}],
            "layer_2": [{"id": "L2-1", "finding": "No control group"}],
        },
    )

    prompt = render_devils_advocate_prompt(
        document=document,
        analysis=analysis,
        skill=skill,
        response_schema={"title": "DevilsAdvocateResult", "type": "object"},
    )

    assert "IC voting orchestrator" in prompt
    assert "Wiki schema contract" in prompt
    assert "Four-section trailer format" in prompt
    assert "Known red-flag patterns" in prompt
    assert "Needs incrementality evidence" in prompt
    assert "Missing incrementality proof" in prompt
    assert "Control group" in prompt
    assert "No control group" in prompt
    assert "Return only JSON matching this schema" in prompt
    assert "DevilsAdvocateResult" in prompt

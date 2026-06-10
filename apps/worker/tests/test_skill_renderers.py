import json
from types import SimpleNamespace
from uuid import uuid4

from skills.devils_advocate_renderer import render_devils_advocate_prompt
from skills.gate2_challenger_renderer import render_gate2_challenger_prompt
from skills.prompt_renderer import render_prompt
from skills.snapshot_loader import load_retrieval_snapshot, load_skill_source_snapshot


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
    assert "assessment_markdown" in prompt
    assert "Оценка документа" in prompt
    assert "layer_1_markdown" in prompt
    assert "do not add Title, Impact, or Recommendation subblocks" in prompt
    assert "layer_1: structured copy of every Layer 1 item with id, severity, issue, evidence." in prompt
    assert "title, issue, evidence, impact, recommendation" not in prompt
    assert "layer_2_markdown" in prompt
    assert "The initiative claims strong MVP traction" in prompt


def test_gate2_challenger_renderer_can_require_english_output():
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
        output_language="en",
    )

    assert "Output language requirement" in prompt
    assert "Write all reader-facing fields in English only" in prompt
    assert "Document assessment" in prompt


def test_gate2_challenger_renderer_includes_devils_advocate_layer_4_context():
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
        layer_4_context={
            "brutal_truth": "Fatal flaw: the investment case has no incrementality proof.",
            "detected_contradictions": [
                {
                    "title": "Gross profit not shown",
                    "body": "Revenue is shown but gross profit is absent.",
                    "severity": "critical",
                }
            ],
            "source": "devils_advocate_predefense",
        },
    )

    assert "Layer 4" in prompt
    assert "Devil's Advocate expert analysis" in prompt
    assert "The Brutal Truth" in prompt
    assert "Fatal flaw: the investment case has no incrementality proof." in prompt
    assert "Detected Contradictions & Missing Proofs" in prompt
    assert "Gross profit not shown" in prompt
    assert "strengthen or supplement Gate Challenger" in prompt


def test_gate2_challenger_renderer_uses_snapshot_files_instead_of_stub_prompt(tmp_path):
    snapshot_dir = tmp_path / "skill-snapshots" / str(uuid4())
    files_dir = snapshot_dir / "files"
    skill_file = files_dir / "skills" / "gate-challenger" / "SKILL.md"
    reference_file = files_dir / "skills" / "gate-challenger" / "references" / "rubric.md"
    reference_file.parent.mkdir(parents=True)
    skill_file.write_text("Snapshot Gate instructions", encoding="utf-8")
    reference_file.write_text("Snapshot reference rubric", encoding="utf-8")
    (snapshot_dir / "manifest.json").write_text(
        json.dumps(
            {
                "source_slug": "gate-challenger",
                "resolved_revision": "abc123",
                "source_fingerprint": "snapshot-fingerprint",
                "files": [
                    {"path": "skills/gate-challenger/SKILL.md", "sha256": "skill-hash"},
                    {"path": "skills/gate-challenger/references/rubric.md", "sha256": "rubric-hash"},
                ],
            }
        ),
        encoding="utf-8",
    )
    document = SimpleNamespace(
        title="Gate 2 defense",
        parsed_text="The initiative claims strong MVP traction but omits cohort evidence.",
        manual_document_type=None,
        detected_document_type="gate_2",
    )
    skill = SimpleNamespace(
        name="gate2_challenger_main_analysis",
        version="baseline",
        prompt_text="Stub prompt should not be used",
        source_uri="/external/gate-challenger",
        source_entrypoint="skills/gate-challenger/SKILL.md",
        source_revision="old",
        source_fingerprint="old",
    )

    prompt = render_gate2_challenger_prompt(
        document=document,
        skill=skill,
        response_schema={"title": "MainAnalysisResult", "type": "object"},
        source_snapshot=load_skill_source_snapshot(str(snapshot_dir)),
    )

    assert "Snapshot Gate instructions" in prompt
    assert "Snapshot reference rubric" in prompt
    assert "source_revision: abc123" in prompt
    assert "source_fingerprint: snapshot-fingerprint" in prompt
    assert "Stub prompt should not be used" not in prompt


def test_gate2_prompt_renderer_requires_snapshot_for_external_snapshot_required_skill():
    document = SimpleNamespace(
        title="Gate 2 defense",
        parsed_text="Document text",
        manual_document_type=None,
        detected_document_type="gate_2",
    )
    skill = SimpleNamespace(
        name="gate2_challenger_main_analysis",
        version="baseline",
        prompt_text="Stub prompt should not be used",
        skill_source_id=uuid4(),
        runtime_mode="snapshot_required",
    )

    try:
        render_prompt(
            document=document,
            skill=skill,
            response_schema={"title": "MainAnalysisResult", "type": "object"},
            run_parameters={},
        )
    except RuntimeError as exc:
        assert str(exc) == "source_snapshot_required"
    else:
        raise AssertionError("expected source_snapshot_required")


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
    assert "native_markdown" in prompt
    assert "The Brutal Truth" in prompt
    assert "Detected Contradictions & Missing Proofs" in prompt
    assert "role_comments" in prompt


def test_devils_advocate_renderer_can_require_english_output(tmp_path):
    (tmp_path / "ic-voting-prompt.md").write_text("IC voting orchestrator", encoding="utf-8")
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
        source_metadata={},
    )
    analysis = SimpleNamespace(
        verdict="need_evidence",
        summary="Needs incrementality evidence.",
        structured_output={"findings": [], "checks": []},
    )

    prompt = render_devils_advocate_prompt(
        document=document,
        analysis=analysis,
        skill=skill,
        response_schema={"title": "DevilsAdvocateResult", "type": "object"},
        output_language="en",
    )

    assert "Output language requirement" in prompt
    assert "Write all reader-facing fields in English only" in prompt
    assert "native_markdown must be written in the requested output language" in prompt


def test_devils_advocate_renderer_uses_source_snapshot_and_retrieval_dossier(tmp_path):
    source_snapshot_dir = tmp_path / "skill-snapshots" / str(uuid4())
    files_dir = source_snapshot_dir / "files"
    case_file = files_dir / "wiki-ic" / "cases" / "incrementality.md"
    pattern_file = files_dir / "wiki-ic" / "patterns" / "missing-proof.md"
    (files_dir / "wiki-ic" / "meta").mkdir(parents=True)
    case_file.parent.mkdir(parents=True, exist_ok=True)
    pattern_file.parent.mkdir(parents=True, exist_ok=True)
    (files_dir / "ic-voting-prompt.md").write_text("Snapshot IC voting orchestrator", encoding="utf-8")
    (files_dir / "wiki-ic" / "schema.md").write_text("Snapshot wiki schema", encoding="utf-8")
    (files_dir / "wiki-ic" / "meta" / "output-format.md").write_text("Snapshot output format", encoding="utf-8")
    case_file.write_text("Snapshot incrementality full case text should not be included", encoding="utf-8")
    pattern_file.write_text("Snapshot missing proof full pattern text should not be included", encoding="utf-8")
    (source_snapshot_dir / "manifest.json").write_text(
        json.dumps(
            {
                "source_slug": "devils-advocate",
                "resolved_revision": "def456",
                "source_fingerprint": "da-source-fingerprint",
                "files": [
                    {"path": "ic-voting-prompt.md", "sha256": "prompt-hash"},
                    {"path": "wiki-ic/schema.md", "sha256": "schema-hash"},
                    {"path": "wiki-ic/meta/output-format.md", "sha256": "format-hash"},
                    {"path": "wiki-ic/cases/incrementality.md", "sha256": "case-hash"},
                    {"path": "wiki-ic/patterns/missing-proof.md", "sha256": "pattern-hash"},
                ],
            }
        ),
        encoding="utf-8",
    )
    retrieval_snapshot_dir = tmp_path / "retrieval-snapshots" / str(uuid4())
    retrieval_snapshot_dir.mkdir(parents=True)
    (retrieval_snapshot_dir / "dossier.json").write_text(
        json.dumps(
            {
                "retrieval_mode": "deterministic_topk",
                "retrieval_version": "deterministic-lexical-v1",
                "corpus_fingerprint": "corpus-fingerprint",
                "query_fingerprint": "query-fingerprint",
                "selected_paths": [
                    "wiki-ic/cases/incrementality.md",
                    "wiki-ic/patterns/missing-proof.md",
                ],
                "selected_items": {
                    "top_cases": [
                        {
                            "path": "wiki-ic/cases/incrementality.md",
                            "score": 4,
                            "excerpt": "Snapshot incrementality excerpt",
                        }
                    ],
                    "top_patterns": [
                        {
                            "path": "wiki-ic/patterns/missing-proof.md",
                            "score": 2,
                            "excerpt": "Snapshot missing proof excerpt",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    document = SimpleNamespace(
        title="Gate 2 defense",
        parsed_text="The document asks for investment approval without incrementality proof.",
        manual_document_type=None,
        detected_document_type="gate_2",
    )
    skill = SimpleNamespace(
        name="devils_advocate_predefense",
        version="baseline",
        prompt_text="Fallback DA prompt should not be used",
        source_uri="/external/devils-advocate/ic-voting-prompt.md",
        source_entrypoint="ic-voting-prompt.md",
        source_revision="old",
        source_fingerprint="old",
        source_metadata={},
    )
    analysis = SimpleNamespace(
        verdict="need_evidence",
        summary="Needs incrementality evidence.",
        structured_output={"findings": [{"id": "F1", "title": "Missing incrementality proof"}], "checks": []},
    )

    prompt = render_devils_advocate_prompt(
        document=document,
        analysis=analysis,
        skill=skill,
        response_schema={"title": "DevilsAdvocateResult", "type": "object"},
        source_snapshot=load_skill_source_snapshot(str(source_snapshot_dir)),
        retrieval_snapshot=load_retrieval_snapshot(str(retrieval_snapshot_dir)),
    )

    assert "Snapshot IC voting orchestrator" in prompt
    assert "Snapshot wiki schema" in prompt
    assert "Snapshot output format" in prompt
    assert "Snapshot incrementality excerpt" in prompt
    assert "Snapshot missing proof excerpt" in prompt
    assert "Snapshot incrementality full case text should not be included" not in prompt
    assert "Snapshot missing proof full pattern text should not be included" not in prompt
    assert "corpus-fingerprint" in prompt
    assert "Needs incrementality evidence" in prompt
    assert "Fallback DA prompt should not be used" not in prompt

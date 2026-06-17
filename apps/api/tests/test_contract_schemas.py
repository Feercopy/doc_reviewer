import json
from pathlib import Path

from jsonschema import ValidationError, validate


SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "contracts" / "schemas"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text())


def role_comment_item(anchor_text: str, body: str, comment_type: str = "missing_data", severity: str = "important") -> dict:
    return {
        "anchor_text": anchor_text,
        "body": body,
        "comment_type": comment_type,
        "severity": severity,
    }


def test_document_parse_artifact_schema_accepts_structured_parse_output():
    schema = load_schema("document-parse-artifact.schema.json")
    payload = {
        "schema_version": "document_parse_artifact.v1",
        "source": {
            "filename": "gate-2.md",
            "mime_type": "text/markdown",
            "sha256": "a" * 64,
            "size_bytes": 42,
        },
        "parser": {
            "name": "utf8_text",
            "version": None,
            "adapter_version": "gate_challenger_parser.v1",
            "options": {},
        },
        "outputs": {
            "plain_text": "# Gate 2\n\nMVP scope",
            "markdown": "# Gate 2\n\nMVP scope",
            "plain_text_sha256": "b" * 64,
            "markdown_sha256": "b" * 64,
        },
        "blocks": [
            {
                "id": "b0001",
                "type": "heading",
                "text": "# Gate 2",
                "markdown": "# Gate 2",
                "page": None,
                "text_span": {"start": 0, "end": 8},
                "hash": "c" * 64,
                "metadata": {},
            }
        ],
        "quality": {
            "char_count": 20,
            "block_count": 1,
            "page_count": None,
            "table_count": 0,
            "empty_pages": [],
            "ocr_used": False,
            "warnings": [],
        },
    }

    validate(instance=payload, schema=schema)


def test_main_analysis_schema_accepts_valid_result():
    schema = load_schema("main-analysis-result.schema.json")
    payload = {
        "verdict": "need_evidence",
        "summary": "Evidence is incomplete.",
        "assessment_markdown": "Оценка документа\nРекомендация: не одобрять полный запуск.",
        "findings": [
            {
                "id": "finding-1",
                "severity": "high",
                "title": "No benchmark baseline",
                "evidence": "Document does not show a baseline.",
            }
        ],
        "checks": [{"name": "Evidence", "status": "partial"}],
        "layer_1_markdown": "Layer 1\nL1-001 — Decision-critical blocker.",
        "layer_1": [
            {
                "id": "L1-001",
                "severity": "critical",
                "issue": "Mandatory TRX-only readiness is not proven.",
                "evidence": "Closure test is planned for Q1 2027.",
            }
        ],
        "layer_2_markdown": "Layer 2\nL2-001 — Atomic weak-link finding.",
        "layer_2": [
            {
                "id": "L2-001",
                "parent_layer_1_id": "L1-001",
                "status": "fail",
                "severity": "high",
                "question": "Does the metric prove the claimed funnel readiness?",
                "answer": "NO",
                "issue": "CR creation to payment missed target.",
                "evidence": "36.7% actual vs >53% target.",
            }
        ],
    }

    validate(instance=payload, schema=schema)


def test_main_analysis_schema_rejects_unknown_verdict():
    schema = load_schema("main-analysis-result.schema.json")
    payload = {
        "verdict": "ship_it",
        "summary": "Invalid.",
        "findings": [],
        "checks": [],
    }

    try:
        validate(instance=payload, schema=schema)
    except ValidationError:
        return

    raise AssertionError("schema accepted an unsupported verdict")


def test_main_analysis_schema_accepts_gate_challenger_parity_fields():
    schema = load_schema("main-analysis-result.schema.json")
    payload = {
        "verdict": "need_evidence",
        "summary": "Evidence is incomplete.",
        "assessment_markdown": "Оценка документа\nРекомендация: не одобрять полный запуск.",
        "findings": [],
        "checks": [],
        "layer_1_markdown": "Layer 1\nL1-001 — Decision-critical blocker.",
        "layer_1": [
            {
                "id": "L1-001",
                "severity": "critical",
                "issue": "Mandatory TRX-only readiness is not proven.",
                "evidence": "Closure test is planned for Q1 2027.",
            }
        ],
        "layer_2_markdown": "Layer 2\nL2-001 — Atomic weak-link finding.",
        "layer_2": [
            {
                "id": "L2-001",
                "parent_layer_1_id": "L1-001",
                "status": "fail",
                "severity": "high",
                "question": "Does the metric prove the claimed funnel readiness?",
                "answer": "NO",
                "issue": "CR creation to payment missed target.",
                "evidence": "36.7% actual vs >53% target.",
            }
        ],
        "narrative_summary": {
            "one_line": "Needs incrementality proof.",
            "decision": "Need evidence before approval.",
        },
        "stage_routing": {
            "document_type": "gate_2",
            "stage": "standard",
            "rationale": "Investment defense document.",
        },
        "approval_scope": {
            "requested_decision": "Approve budget",
            "approved_scope": "Not approved yet",
            "conditions": ["Add control group readout"],
        },
        "layer_3": [{"id": "L3-1", "risk": "Committee escalation"}],
        "merged_blockers": [{"id": "B1", "summary": "No incrementality proof"}],
    }

    validate(instance=payload, schema=schema)


def test_main_analysis_schema_rejects_expanded_layer_1_fields():
    schema = load_schema("main-analysis-result.schema.json")
    payload = {
        "verdict": "need_evidence",
        "summary": "Evidence is incomplete.",
        "assessment_markdown": "Оценка документа\nРекомендация: не одобрять полный запуск.",
        "findings": [],
        "checks": [],
        "layer_1_markdown": "Layer 1\nL1-001 — Decision-critical blocker.",
        "layer_1": [
            {
                "id": "L1-001",
                "severity": "critical",
                "title": "Decision-critical blocker",
                "issue": "Mandatory TRX-only readiness is not proven.",
                "evidence": "Closure test is planned for Q1 2027.",
                "impact": "Committee cannot approve scale-up as-is.",
                "recommendation": "Gate scale-up on closure-test results.",
            }
        ],
        "layer_2_markdown": "Layer 2\nL2-001 — Atomic weak-link finding.",
        "layer_2": [
            {
                "id": "L2-001",
                "parent_layer_1_id": "L1-001",
                "status": "fail",
                "severity": "high",
                "question": "Does the metric prove the claimed funnel readiness?",
                "answer": "NO",
                "issue": "CR creation to payment missed target.",
                "evidence": "36.7% actual vs >53% target.",
            }
        ],
    }

    try:
        validate(instance=payload, schema=schema)
    except ValidationError:
        return

    raise AssertionError("schema accepted expanded Layer 1 fields")


def test_main_analysis_schema_rejects_non_skill_layer_2_fields():
    schema = load_schema("main-analysis-result.schema.json")
    payload = {
        "verdict": "need_evidence",
        "summary": "Evidence is incomplete.",
        "assessment_markdown": "Оценка документа\nРекомендация: не одобрять полный запуск.",
        "findings": [],
        "checks": [],
        "layer_1_markdown": "Layer 1\nL1-001 — Decision-critical blocker.",
        "layer_1": [
            {
                "id": "L1-001",
                "severity": "critical",
                "issue": "Mandatory TRX-only readiness is not proven.",
                "evidence": "Closure test is planned for Q1 2027.",
            }
        ],
        "layer_2_markdown": "Layer 2\nL2-001 — Atomic weak-link finding.",
        "layer_2": [
            {
                "id": "L2-001",
                "parent_layer_1_id": "L1-001",
                "status": "fail",
                "severity": "high",
                "question": "Does the metric prove the claimed funnel readiness?",
                "answer": "NO",
                "issue": "CR creation to payment missed target.",
                "evidence": "36.7% actual vs >53% target.",
                "risk": "Funnel economics are not de-risked.",
                "recommendation": "Show funnel recovery before resource approval.",
            }
        ],
    }

    try:
        validate(instance=payload, schema=schema)
    except ValidationError:
        return

    raise AssertionError("schema accepted non-skill Layer 2 risk/recommendation fields")


def test_main_analysis_summary_schema_accepts_staged_summary_result():
    schema = load_schema("main-analysis-summary-result.schema.json")
    payload = {
        "verdict": "need_evidence",
        "summary": "Evidence is incomplete.",
        "assessment_markdown": "Оценка документа\nРекомендация: запросить доказательства.",
        "layer_1_index": [
            {
                "id": "l1-traction",
                "severity": "high",
                "issue": "Traction evidence is not decision-grade.",
                "evidence_anchor": "FAQ 4: CR target is planned, not proven.",
            }
        ],
        "layer_2_index": [
            {
                "id": "l2-traction-1",
                "parent_layer_1_id": "l1-traction",
                "status": "fail",
                "severity": "high",
                "question": "Does the document prove traction with decision-grade evidence?",
                "answer": "NO",
                "short_evidence": "The document gives a plan but no measured result.",
            }
        ],
        "details_status": "not_requested",
        "details_run_id": None,
        "revision_required": False,
        "revision_reason": None,
    }

    validate(instance=payload, schema=schema)


def test_main_analysis_details_schema_accepts_lazy_layer_details_result():
    schema = load_schema("main-analysis-details-result.schema.json")
    payload = {
        "analysis_id": "00000000-0000-0000-0000-000000000123",
        "verdict": "need_evidence",
        "summary": "Evidence is incomplete.",
        "layer_1_markdown": "Layer 1\nL1-001 — Decision-critical blocker.",
        "layer_1": [
            {
                "id": "L1-001",
                "severity": "high",
                "issue": "Traction evidence is not decision-grade.",
                "evidence": "FAQ 4 states the target but not the measured result.",
            }
        ],
        "layer_2_markdown": "Layer 2\nL2-001 — Atomic weak-link finding.",
        "layer_2": [
            {
                "id": "L2-001",
                "parent_layer_1_id": "L1-001",
                "status": "fail",
                "severity": "high",
                "question": "Does the document prove traction with decision-grade evidence?",
                "answer": "NO",
                "evidence": "The target is planned, not measured.",
                "issue": "The evidence does not close the traction proof.",
            }
        ],
        "revision_required": False,
        "revision_reason": None,
    }

    validate(instance=payload, schema=schema)


def test_devils_advocate_schema_accepts_retrieval_context():
    schema = load_schema("devils-advocate-result.schema.json")
    payload = {
        "run_mode": "full_ic_voting",
        "native_markdown": (
            "🔴 Devil's Advocate — IC+Gate 3: Safe Deal\n\n"
            "Pre-flight summary\n- Stage: Gate-3\n\n---\nThe Brutal Truth\n\nFatal flaw.\n\n"
            "---\nDetected Contradictions & Missing Proofs\n\n- Missing proof.\n\n"
            "---\nThe \"Tough Co-CEO\" Questions\n\n1. What is incremental?\n\n"
            "---\nActionable JTBDs\n\n1. Add a hard KPI gate.\n\n"
            "=== IC Decision ===\nVerdict: Rework"
        ),
        "preflight_summary": ["Stage: Gate-3"],
        "brutal_truth": "Fatal flaw.",
        "detected_contradictions": [
            {
                "section": "FAQ 4",
                "title": "Gross profit not shown",
                "body": "Revenue is shown but gross profit is absent.",
                "comment_type": "missing_data",
                "severity": "critical",
                "citations": ["[[financial-revenue-and-gross-profit]]"],
            }
        ],
        "role_comments": [
            {
                "voter": "MP",
                "vote": "reject",
                "rationale": "No incrementality proof.",
                "comments": [role_comment_item("CR contact to payment", "What is the baseline and control group?", severity="critical")],
            },
            {
                "voter": "CPO",
                "vote": "reject",
                "rationale": "Funnel target missed.",
                "comments": [role_comment_item("CR contact to payment", "Which product change closes the funnel gap?")],
            },
            {
                "voter": "TechDir",
                "vote": "reject",
                "rationale": "No A/B delta.",
                "comments": [role_comment_item("A/B delta", "Where is the experiment readout?", "methodology_issue")],
            },
            {
                "voter": "VertDir",
                "vote": "approve",
                "rationale": "Direction is useful.",
                "comments": [role_comment_item("Business Services", "Keep the vertical rollout gated by evidence.", "risk_not_addressed", "minor")],
            },
        ],
        "tough_questions": [
            {"question": "What is incremental impact?", "persona": "[[persona-managing-partner]]"},
            {"question": "Why is Stage 2 treated as proven?", "persona": "[[persona-product-director]]"},
            {"question": "Where is the A/B delta?", "persona": "[[persona-technical-director]]"},
        ],
        "actionable_jtbds": [
            "Set a hard closure-test KPI gate.",
            "Show gross profit and cumulative uplift.",
            "Separate Stage 1 from Stage 2 HC ask.",
        ],
        "anchored_comments": [],
        "trailer": {
            "executive_summary": "Needs evidence.",
            "key_risks": ["weak proof"],
            "missing_evidence": ["control group"],
            "next_steps": ["add experiment readout"],
        },
        "ic_decision": {
            "verdict": "rework",
            "vote_tally": {"MP": "reject", "CPO": "reject", "TechDir": "reject", "VertDir": "approve"},
            "rationale": "Missing proof.",
            "conditions": ["Set a hard closure-test KPI gate."],
            "heuristics_fired": ["[[financial-hockey-stick]]"],
            "patterns_fired": ["[[experimental-traction-gap]]"],
            "precedents_anchored": ["[[ic-2025-292]]"],
            "next_ic": "Q1 2027 after closure-test results",
        },
        "predicted_questions": ["What is incremental impact?"],
        "consulted_wiki_pages": ["wiki-ic/cases/incrementality.md"],
        "source_citations": ["wiki-ic/cases/incrementality.md"],
        "retrieval": {
            "retrieval_mode": "deterministic_topk",
            "corpus_fingerprint": "corpus-fingerprint",
            "selected_cases": ["wiki-ic/cases/incrementality.md"],
            "selected_patterns": ["wiki-ic/patterns/missing-proof.md"],
            "selected_questions": ["What is the control group?"],
        },
    }

    validate(instance=payload, schema=schema)


def test_devils_advocate_schema_requires_original_skill_role_comment_shape():
    schema = load_schema("devils-advocate-result.schema.json")
    payload = {
        "run_mode": "full_ic_voting",
        "native_markdown": "The Brutal Truth\n\nFatal flaw.\n\n=== IC Decision ===\nVerdict: Rework",
        "preflight_summary": ["Stage: Gate-3"],
        "brutal_truth": "Fatal flaw.",
        "detected_contradictions": [],
        "role_comments": [
            {
                "voter": "MP",
                "vote": "reject",
                "rationale": "No incrementality proof.",
                "comments": [
                    {
                        "anchor_text": "CR contact to payment",
                        "body": "What is the baseline and control group?",
                        "comment_type": "missing_data",
                        "severity": "critical",
                    }
                ],
            },
            {
                "voter": "CPO",
                "vote": "reject",
                "rationale": "Funnel target missed.",
                "comments": [role_comment_item("CR contact to payment", "Which product change closes the funnel gap?")],
            },
            {
                "voter": "TechDir",
                "vote": "reject",
                "rationale": "No A/B delta.",
                "comments": [role_comment_item("A/B delta", "Where is the experiment readout?", "methodology_issue")],
            },
            {
                "voter": "VertDir",
                "vote": "approve",
                "rationale": "Direction is useful.",
                "comments": [role_comment_item("Business Services", "Keep the vertical rollout gated by evidence.", "risk_not_addressed", "minor")],
            },
        ],
        "tough_questions": [
            {"question": "What is incremental impact?", "persona": "[[persona-managing-partner]]"},
            {"question": "Why is Stage 2 treated as proven?", "persona": "[[persona-product-director]]"},
            {"question": "Where is the A/B delta?", "persona": "[[persona-technical-director]]"},
        ],
        "actionable_jtbds": [
            "Set a hard closure-test KPI gate.",
            "Show gross profit and cumulative uplift.",
            "Separate Stage 1 from Stage 2 HC ask.",
        ],
        "ic_decision": {
            "verdict": "rework",
            "vote_tally": {"MP": "reject", "CPO": "reject", "TechDir": "reject", "VertDir": "approve"},
            "rationale": "Missing proof.",
            "conditions": ["Set a hard closure-test KPI gate."],
            "heuristics_fired": ["[[financial-hockey-stick]]"],
            "patterns_fired": ["[[experimental-traction-gap]]"],
            "precedents_anchored": ["[[ic-2025-292]]"],
            "next_ic": "Q1 2027 after closure-test results",
        },
        "consulted_wiki_pages": ["wiki-ic/cases/incrementality.md"],
        "source_citations": ["wiki-ic/cases/incrementality.md"],
        "retrieval": {"retrieval_mode": "deterministic_topk"},
    }

    validate(instance=payload, schema=schema)


def test_devils_advocate_schema_rejects_empty_role_comment_items():
    schema = load_schema("devils-advocate-result.schema.json")
    payload = {
        "run_mode": "full_ic_voting",
        "native_markdown": "The Brutal Truth\n\nFatal flaw.\n\n=== IC Decision ===\nVerdict: Rework",
        "preflight_summary": ["Stage: Gate-3"],
        "brutal_truth": "Fatal flaw.",
        "detected_contradictions": [],
        "role_comments": [
            {"voter": "MP", "vote": "reject", "rationale": "No incrementality proof.", "comments": []},
            {"voter": "CPO", "vote": "reject", "rationale": "Funnel target missed.", "comments": []},
            {"voter": "TechDir", "vote": "reject", "rationale": "No A/B delta.", "comments": []},
            {"voter": "VertDir", "vote": "reject", "rationale": "Vertical rollout is not proven.", "comments": []},
        ],
        "tough_questions": [
            {"question": "What is incremental impact?", "persona": "[[persona-managing-partner]]"},
            {"question": "Why is Stage 2 treated as proven?", "persona": "[[persona-product-director]]"},
            {"question": "Where is the A/B delta?", "persona": "[[persona-technical-director]]"},
        ],
        "actionable_jtbds": [
            "Set a hard closure-test KPI gate.",
            "Show gross profit and cumulative uplift.",
            "Separate Stage 1 from Stage 2 HC ask.",
        ],
        "ic_decision": {
            "verdict": "rework",
            "vote_tally": {"MP": "reject", "CPO": "reject", "TechDir": "reject", "VertDir": "reject"},
            "rationale": "Missing proof.",
            "conditions": ["Set a hard closure-test KPI gate."],
            "heuristics_fired": ["[[financial-hockey-stick]]"],
            "patterns_fired": ["[[experimental-traction-gap]]"],
            "precedents_anchored": ["[[ic-2025-292]]"],
            "next_ic": "Q1 2027 after closure-test results",
        },
        "consulted_wiki_pages": ["wiki-ic/cases/incrementality.md"],
        "source_citations": ["wiki-ic/cases/incrementality.md"],
        "retrieval": {"retrieval_mode": "deterministic_topk"},
    }

    try:
        validate(instance=payload, schema=schema)
    except ValidationError:
        return

    raise AssertionError("schema accepted role comments without comment rows")

import json
from pathlib import Path

from jsonschema import ValidationError, validate


SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "contracts" / "schemas"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text())


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
                "severity": "high",
                "title": "Atomic weak-link finding",
                "atomic_issue": "CR creation to payment missed target.",
                "evidence": "36.7% actual vs >53% target.",
                "risk": "Funnel economics are not de-risked.",
                "recommendation": "Show funnel recovery before resource approval.",
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
                "severity": "high",
                "title": "Atomic weak-link finding",
                "atomic_issue": "CR creation to payment missed target.",
                "evidence": "36.7% actual vs >53% target.",
                "risk": "Funnel economics are not de-risked.",
                "recommendation": "Show funnel recovery before resource approval.",
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
            {"voter": "MP", "vote": "reject", "rationale": "No incrementality proof.", "comments": []},
            {"voter": "CPO", "vote": "reject", "rationale": "Funnel target missed.", "comments": []},
            {"voter": "TechDir", "vote": "reject", "rationale": "No A/B delta.", "comments": []},
            {"voter": "VertDir", "vote": "approve", "rationale": "Direction is useful.", "comments": []},
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

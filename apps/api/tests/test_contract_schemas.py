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


def test_benchmark_judge_schema_accepts_v2_result():
    schema = load_schema("benchmark-judge-result.schema.json")
    payload = {
        "layer_1": {
            "n_ref": 1,
            "n_pred": 1,
            "score_sum": 1.0,
            "precision": 100.0,
            "recall": 100.0,
            "f1": 100.0,
            "matched": [
                {
                    "ref_id": "L1-001",
                    "block": "go_to_market",
                    "expected": "Missing evidence for repeatable acquisition.",
                    "actual": "The document does not prove repeatable acquisition.",
                    "score": 1.0,
                    "comment": "Same decision-critical gap.",
                    "mapping_note": "Direct semantic match.",
                }
            ],
            "missed_issues": [],
            "false_positives": [],
            "duplicates": [],
            "summary": "Layer 1 matched fully.",
        },
        "layer_2": {
            "n_ref": 2,
            "n_pred": 2,
            "score_sum": 1.5,
            "precision": 75.0,
            "recall": 75.0,
            "f1": 75.0,
            "matched": [
                {
                    "ref_id": "L2-001",
                    "block": "metrics",
                    "expected": "CR target is planned, not measured.",
                    "actual": "The funnel target is not proven by measured results.",
                    "score": 0.5,
                    "comment": "Partial evidence match.",
                    "mapping_note": "Same metric, weaker specificity.",
                }
            ],
            "missed_issues": [
                {
                    "ref_id": "L2-002",
                    "block": "unit_economics",
                    "expected": "Gross profit bridge is absent.",
                    "reason": "No comparable actual issue.",
                }
            ],
            "false_positives": [
                {
                    "pred_id": "L2-extra",
                    "block": "ops",
                    "actual": "Operational dependency is unsupported.",
                    "type": "unsupported_or_wrong",
                    "reason": "No evidence in source document.",
                }
            ],
            "duplicates": [
                {
                    "pred_id": "L2-dup",
                    "duplicates_ref_id": "L2-001",
                    "reason": "Repeats the same funnel gap.",
                }
            ],
            "summary": "Layer 2 is partially matched.",
        },
        "overall": {
            "n_ref_total": 3,
            "n_pred_total": 3,
            "score_sum_total": 2.5,
            "precision": 83.33,
            "recall": 83.33,
            "f1": 83.33,
        },
        "diagnostics": {
            "valid_extra_insights_count": 0,
            "unsupported_or_wrong_false_positives_count": 1,
            "duplicate_count": 1,
            "main_reasons": ["Layer 2 missed one unit economics issue."],
            "strengths": ["Layer 1 matched the core blocker."],
        },
        "recommendations": ["Tighten metric-level evidence extraction."],
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

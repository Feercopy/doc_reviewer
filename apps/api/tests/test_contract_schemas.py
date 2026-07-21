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


def ic_role_full_report_materials() -> dict:
    return {
        "section_drafts": [
            {
                "section_key": "section_4",
                "title": "Financial model review",
                "content": "Detailed role-level material for the full investment committee report.",
                "evidence_ids": ["doc-001"],
            }
        ],
        "tables": [
            {
                "section_key": "section_4",
                "title": "Key numbers",
                "markdown": "| Metric | Value |\n|---|---|\n| Budget | 12000000 |",
            }
        ],
        "risks": [{"title": "Model dependency", "detail": "The model depends on unverified assumptions.", "severity": "critical"}],
        "data_gaps": [{"title": "Cohort proof", "detail": "Cohort proof is missing."}],
        "recommendations": [{"title": "Add evidence", "detail": "Add measured evidence before approval."}],
        "scenarios": [{"title": "Base", "detail": "Base case depends on the stated assumptions."}],
        "primary_verify_notes": ["Financial auditor is primary for section_4."],
    }


def ic_review_minimal_payload() -> dict:
    return {
        "run_mode": "ic_agentic_review_compact",
        "verdict": "UNKNOWN",
        "executive_brief": "TBD after IC role synthesis. " * 16,
        "confidence": 0.0,
        "top_findings": [],
        "key_numbers": [],
        "spreadsheet_audit": {
            "status": "not_provided",
            "summary": "",
            "formula_issues_count": 0,
            "critical_formula_issues_count": 0,
            "source_filename": None,
        },
        "critical_risks": [],
        "data_gaps": [],
        "required_actions": [],
        "questions_for_team": [],
        "role_summaries": [],
        "validation": {
            "status": "not_run",
            "summary": "",
            "warnings_count": 0,
            "failures_count": 0,
        },
        "artifacts": [],
    }


def ic_review_full_payload() -> dict:
    payload = ic_review_minimal_payload()
    payload.update(
        {
            "verdict": "CONDITIONAL",
            "executive_brief": "The IC should not approve full scale yet. " * 14,
            "confidence": 0.74,
            "top_findings": [
                {
                    "title": "Financial model does not prove payback",
                    "severity": "critical",
                    "summary": "Unit economics depend on a conversion uplift that is not supported by cohort evidence.",
                    "evidence": "Workbook sheet PnL assumes 18% conversion uplift without a measured baseline.",
                    "recommendation": "Require a measured cohort bridge before budget approval.",
                },
                {
                    "title": "Market sizing overstates reachable demand",
                    "severity": "high",
                    "summary": "The proposal uses total category demand instead of serviceable demand for the launch segment.",
                    "evidence": "Document section 3 uses national TAM while launch scope is two cities.",
                    "recommendation": "Rebuild sizing from reachable active sellers and observed attach rates.",
                },
                {
                    "title": "Legal dependency is not owned",
                    "severity": "medium",
                    "summary": "A required policy change is mentioned but has no owner, milestone, or fallback path.",
                    "evidence": "Risk table lists policy approval as external dependency.",
                    "recommendation": "Add owner, approval date, and no-go fallback before launch.",
                },
            ],
            "key_numbers": [
                {
                    "label": "Requested budget",
                    "value": "12000000",
                    "unit": "RUB",
                    "source": "Document section 5",
                }
            ],
            "spreadsheet_audit": {
                "status": "completed",
                "summary": "Workbook was parsed and formula checks completed with one critical issue.",
                "formula_issues_count": 4,
                "critical_formula_issues_count": 1,
                "source_filename": "model.xlsx",
            },
            "critical_risks": [
                "Conversion uplift is assumed, not measured.",
                "Sales capacity plan lacks ramp constraints.",
                "Legal approval can delay launch past the claimed payback window.",
            ],
            "data_gaps": [
                "No cohort payback by acquisition channel.",
                "No sensitivity table for price discount depth.",
                "No owner for compliance dependency.",
            ],
            "required_actions": [
                "Add measured baseline and uplift proof.",
                "Rebuild market sizing for launch geography.",
                "Add signed legal dependency owner and deadline.",
            ],
            "questions_for_team": [
                "What measured cohort proves the conversion uplift?",
                "Which sellers are included in serviceable launch demand?",
                "What is the fallback if legal approval slips by one quarter?",
            ],
            "role_summaries": [
                {
                    "role": "ic-financial-auditor",
                    "summary": "The financial audit found that payback depends on uplift assumptions that are not backed by source evidence or sensitivity analysis.",
                },
                {
                    "role": "ic-product-analyst",
                    "summary": "The product review found a plausible customer problem, but activation proof and launch readiness metrics are still incomplete.",
                },
                {
                    "role": "ic-risk-scenario",
                    "summary": "The risk scenario review identified legal timing and funnel sensitivity as the primary approval conditions for the committee.",
                },
                {
                    "role": "ic-market-analyst",
                    "summary": "The market analyst found that serviceable demand needs a narrower launch-segment calculation before the committee can trust the upside case.",
                },
                {
                    "role": "ic-web-researcher",
                    "summary": "The web researcher summary is constrained to provided materials in this MVP and highlights missing external validation as a decision caveat.",
                },
                {
                    "role": "ic-benchmark-valuation",
                    "summary": "The benchmark valuation review found that comparable cases are directionally useful but not strong enough to support the requested valuation uplift.",
                },
                {
                    "role": "ic-team-legal",
                    "summary": "The team and legal review found unresolved policy ownership and launch dependency risks that should become explicit approval conditions.",
                },
                {
                    "role": "ic-tech-dd",
                    "summary": "The technical due diligence review found no fatal architecture blocker, but launch readiness still depends on operational monitoring and rollback proof.",
                },
            ],
            "validation": {
                "status": "warn",
                "summary": "Structured result validates, but source evidence coverage is incomplete.",
                "warnings_count": 2,
                "failures_count": 0,
            },
            "artifacts": [
                {
                    "kind": "validation_report",
                    "filename": "validation_report.txt",
                    "summary": "Validation completed with warnings.",
                }
            ],
        }
    )
    return payload


def assert_schema_rejects(payload: dict, schema: dict, message: str) -> None:
    try:
        validate(instance=payload, schema=schema)
    except ValidationError:
        return

    raise AssertionError(message)


IC_AGENTIC_ROLES = [
    "ic-financial-auditor",
    "ic-product-analyst",
    "ic-market-analyst",
    "ic-web-researcher",
    "ic-benchmark-valuation",
    "ic-team-legal",
    "ic-tech-dd",
    "ic-risk-scenario",
]


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


def test_ic_agentic_review_schema_accepts_minimal_compact_result():
    schema = load_schema("ic-agentic-review-result.schema.json")

    validate(instance=ic_review_minimal_payload(), schema=schema)


def test_result_short_summary_schema_accepts_llm_synthesis_payload():
    schema = load_schema("result-short-summary.schema.json")

    validate(
        instance={
            "run_mode": "result_short_summary",
            "short_summary": (
                "Gate Challenger and IC Review both point to a conditional decision: the case has a coherent "
                "business direction, but approval should wait until the team closes the evidence gaps, validates "
                "unit economics, and documents the risk mitigations needed for an IC-ready launch."
            ),
        },
        schema=schema,
    )


def test_result_rationale_schema_accepts_llm_synthesis_payload():
    schema = load_schema("result-rationale.schema.json")

    validate(
        instance={
            "run_mode": "result_rationale",
            "rationale_markdown": (
                "Оценка остается условной: Gate Challenger фиксирует, что ключевые доказательства пока "
                "не закрывают полный масштаб, а IC Review усиливает этот вывод через finding по модели, "
                "где финансовые допущения и uplift-механики требуют дополнительной проверки перед полным approval."
            ),
            "rationale_items": [
                {
                    "title": "Главный uplift не доказан текущей фактической дельтой.",
                    "detail": (
                        "Gate Challenger фиксирует отсутствие текущей A/B delta, а IC Review показывает, "
                        "что финансовая модель опирается на внешние и исторические бенчмарки."
                    ),
                    "sources": ["gate_challenger", "ic_review"],
                }
            ],
            "critical_risks": ["Full rollout may lock in hiring before uplift is proven."],
            "data_gaps": ["Missing current A/B delta tied to the requested investment case."],
        },
        schema=schema,
    )


def test_ic_agentic_review_schema_accepts_full_compact_result():
    schema = load_schema("ic-agentic-review-result.schema.json")

    validate(instance=ic_review_full_payload(), schema=schema)


def test_ic_agentic_role_schema_accepts_each_original_role_result():
    schema = load_schema("ic-agentic-role-result.schema.json")

    for role in IC_AGENTIC_ROLES:
        payload = {
            "role": role,
            "section_keys": ["section_4"],
            "summary": "Role-level finding summary.",
            "findings": [
                {
                    "title": "Finding title",
                    "severity": "critical",
                    "evidence": "Document or workbook-grounded evidence.",
                    "recommendation": "Specific remediation.",
                }
            ],
            "data_gaps": [],
            "numbers_used": [],
            "full_report_materials": ic_role_full_report_materials(),
        }

        validate(instance=payload, schema=schema)


def test_ic_agentic_review_schema_rejects_unsupported_verdict():
    schema = load_schema("ic-agentic-review-result.schema.json")
    payload = ic_review_minimal_payload()
    payload["verdict"] = "REWORK"

    assert_schema_rejects(payload, schema, "schema accepted an unsupported IC review verdict")


def test_ic_agentic_review_schema_rejects_missing_spreadsheet_audit_status():
    schema = load_schema("ic-agentic-review-result.schema.json")
    payload = ic_review_minimal_payload()
    del payload["spreadsheet_audit"]["status"]

    assert_schema_rejects(payload, schema, "schema accepted spreadsheet_audit without status")


def test_ic_agentic_review_schema_rejects_more_than_seven_top_findings():
    schema = load_schema("ic-agentic-review-result.schema.json")
    payload = ic_review_full_payload()
    payload["top_findings"] = payload["top_findings"] + [
        {
            "title": f"Extra finding {index}",
            "severity": "info",
            "summary": "Additional UI row that should exceed the compact display bound.",
            "evidence": "Synthetic evidence for bounds testing.",
            "recommendation": "Trim compact findings before persistence.",
        }
        for index in range(5)
    ]

    assert_schema_rejects(payload, schema, "schema accepted more than 7 top_findings")


def test_ic_agentic_review_schema_rejects_extra_nested_finding_field():
    schema = load_schema("ic-agentic-review-result.schema.json")
    payload = ic_review_full_payload()
    payload["top_findings"][0]["owner"] = "finance"

    assert_schema_rejects(payload, schema, "schema accepted unexpected nested field in top_findings")


def test_ic_agentic_role_schema_rejects_extra_nested_finding_field():
    schema = load_schema("ic-agentic-role-result.schema.json")
    payload = {
        "role": "ic-financial-auditor",
        "section_keys": ["section_4"],
        "summary": "Role-level finding summary.",
        "findings": [
            {
                "title": "Finding title",
                "severity": "critical",
                "evidence": "Document or workbook-grounded evidence.",
                "recommendation": "Specific remediation.",
                "owner": "finance",
            }
        ],
        "data_gaps": [],
        "numbers_used": [],
        "full_report_materials": ic_role_full_report_materials(),
    }

    assert_schema_rejects(payload, schema, "schema accepted unexpected nested field in role finding")


def test_ic_agentic_role_schema_rejects_unbounded_arrays():
    schema = load_schema("ic-agentic-role-result.schema.json")
    finding = {
        "title": "Finding title",
        "severity": "critical",
        "evidence": "Document or workbook-grounded evidence.",
        "recommendation": "Specific remediation.",
    }
    number_used = {"label": "Budget", "value": "12000000", "source": "Document section 5"}

    for field, value in [
        ("section_keys", [f"section_{index}" for index in range(21)]),
        ("findings", [finding for _ in range(21)]),
        ("data_gaps", [f"Missing data gap {index}" for index in range(21)]),
        ("numbers_used", [number_used for _ in range(31)]),
    ]:
        payload = {
            "role": "ic-financial-auditor",
            "section_keys": ["section_4"],
            "summary": "Role-level finding summary.",
            "findings": [finding],
            "data_gaps": [],
            "numbers_used": [],
            "full_report_materials": ic_role_full_report_materials(),
        }
        payload[field] = value

        assert_schema_rejects(payload, schema, f"schema accepted too many {field}")

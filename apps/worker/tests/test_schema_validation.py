import json

from results import schema_validation


def test_parse_json_output_unwraps_chat_completion_envelope():
    structured_text = json.dumps(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({"summary": "ok", "findings": []}),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
    )

    payload = schema_validation.parse_json_output(structured_text)

    assert payload == {"summary": "ok", "findings": []}


def test_parse_json_output_unwraps_fenced_json_inside_chat_completion_envelope():
    structured_text = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": '\n```json\n{"summary": "ok"}\n```',
                    },
                }
            ],
        }
    )

    payload = schema_validation.parse_json_output(structured_text)

    assert payload == {"summary": "ok"}


def test_parse_and_validate_json_output_moves_ic_role_primary_verify_notes_to_report_materials():
    payload = {
        "role": "ic-product-analyst",
        "section_keys": ["5"],
        "summary": "Product summary.",
        "findings": [],
        "data_gaps": [],
        "numbers_used": [],
        "full_report_materials": {
            "section_drafts": [],
            "tables": [],
            "risks": [],
            "data_gaps": [],
            "recommendations": [],
            "scenarios": [],
        },
        "primary_verify_notes": ["Primary owner note."],
    }

    normalized = schema_validation.parse_and_validate_json_output(
        structured_text=json.dumps(payload),
        schema_path="contracts/schemas/ic-agentic-role-result.schema.json",
    )

    assert "primary_verify_notes" not in normalized
    assert normalized["full_report_materials"]["primary_verify_notes"] == ["Primary owner note."]


def test_parse_and_validate_json_output_accepts_fenced_json(tmp_path, monkeypatch):
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["summary"],
                "properties": {"summary": {"type": "string"}},
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(schema_validation, "_resolve_schema_path", lambda _: schema_path)

    payload = schema_validation.parse_and_validate_json_output(
        structured_text='\n\n```json\n{"summary": "ok"}\n```',
        schema_path="unused.schema.json",
    )

    assert payload == {"summary": "ok"}


def test_parse_and_validate_json_output_accepts_literal_tabs_inside_json_strings(tmp_path, monkeypatch):
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["anchor_text"],
                "properties": {"anchor_text": {"type": "string"}},
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(schema_validation, "_resolve_schema_path", lambda _: schema_path)

    payload = schema_validation.parse_and_validate_json_output(
        structured_text='{"anchor_text": "Cost allocation, %\t3%\t37%"}',
        schema_path="unused.schema.json",
    )

    assert payload == {"anchor_text": "Cost allocation, %\t3%\t37%"}


def test_parse_and_validate_json_output_normalizes_devils_advocate_markdown_only_result():
    markdown = """# 🔴 Devil's Advocate — SD Business Services (Gate 3)

## Pre-flight summary
- **Инициатива:** Safe Deal in Business Services
- **Оценка документа:** Нужна доработка доказательной базы.

## The Brutal Truth
Проект масштабирует непроверенную модель без достаточного подтверждения PMF.

## Detected Contradictions & Missing Proofs

### 1. Baseline is missing
- **Раздел:** FAQ 4
- **Суть:** Base scenario is empty, so incrementality cannot be verified.
- **Severity:** Critical
- **Citations:** "Base scenario - ..."

## Role comments / voter synthesis

### Managing Partner [MP] — Голос: Против (Reject)
**Рациональное:** Resource ask is not justified by pilot traction.
- **Анализ анкоров в тексте:**
  * *"39,5 add resources"* — Too much hiring before PMF proof.

### CPO [CPO] — Голос: Против (Reject)
**Рациональное:** Product activation is below target.
- **Анализ анкоров в тексте:**
  * *"Share of contacts through SD button = 1,2%"* — Weak activation.

### Technical Director [TechDir] — Голос: Против (Reject)
**Рациональное:** Required integration is still in backlog.
- **Анализ анкоров в тексте:**
  * *"API Improvements for CRM Integrations"* — Critical dependency is not ready.

### Vertical Director [VertDir] — Голос: Против (Reject)
**Рациональное:** Cannibalization baseline is not evidenced.
- **Анализ анкоров в тексте:**
  * *"Base scenario"* — Missing category baseline.

## The "Tough Co-CEO" Questions
1. *(В стиле [[persona-managing-partner]])* Why approve hiring before PMF?
2. *(В стиле [[persona-product-director]])* How will activation recover?
3. *(В стиле [[persona-technical-director]])* When will CRM integration be ready?

## Actionable JTBDs
1. **KPI gate:** Prove activation on a stable cohort.
2. **Fintech/GR signoff:** Confirm legal and technical flow.
3. **Cannibalization matrix:** Show category-level classified baseline.

=== IC Decision ===
**Verdict:** Rework
**Vote tally:** MP=reject · CPO=reject · TechDir=reject · VertDir=reject
**Rationale:** Missing PMF and baseline proof.

**Conditions to close before resubmission:**
1. Cut hiring request.
2. Fill the baseline model.

**Heuristics fired:**
- [[experimental-traction-gap]]

**Patterns fired:**
- [[red-flag-extra-hc-unmet-baseline]]

**Precedents anchored:**
- [[ic-2025-292]]

**Next IC:** Progress review after evidence update.
"""

    payload = schema_validation.parse_and_validate_json_output(
        structured_text=json.dumps({"run_mode": "full_ic_voting", "native_markdown": markdown}),
        schema_path="contracts/schemas/devils-advocate-result.schema.json",
    )

    assert payload["preflight_summary"] == [
        "**Инициатива:** Safe Deal in Business Services",
        "**Оценка документа:** Нужна доработка доказательной базы.",
    ]
    assert payload["brutal_truth"].startswith("Проект масштабирует")
    assert payload["detected_contradictions"][0]["title"] == "Baseline is missing"
    assert payload["role_comments"][0]["voter"] == "MP"
    assert payload["role_comments"][0]["comments"][0]["anchor_text"] == "39,5 add resources"
    assert payload["tough_questions"][0]["persona"] == "[[persona-managing-partner]]"
    assert payload["actionable_jtbds"][0].startswith("**KPI gate:**")
    assert payload["ic_decision"]["verdict"] == "rework"
    assert payload["ic_decision"]["vote_tally"] == {
        "MP": "reject",
        "CPO": "reject",
        "TechDir": "reject",
        "VertDir": "reject",
    }


def test_parse_and_validate_json_output_enforces_stage_checklist_for_document_type():
    payload = schema_validation.parse_and_validate_json_output(
        structured_text=json.dumps(_main_analysis_result_payload()),
        schema_path="contracts/schemas/main-analysis-result.schema.json",
        document_type="gate_2",
        enforce_stage_checklist=True,
    )

    assert [item["id"] for item in payload["stage_checklist"]] == [
        "gate2_hypothesis_results",
        "gate2_mvp_or_target_product",
        "gate2_mockups_or_user_flow",
        "gate2_gate3_commitments",
    ]


def test_parse_and_validate_json_output_rejects_partial_stage_checklist_for_document_type():
    payload = _main_analysis_result_payload()
    payload["stage_checklist"] = payload["stage_checklist"][:1]

    try:
        schema_validation.parse_and_validate_json_output(
            structured_text=json.dumps(payload),
            schema_path="contracts/schemas/main-analysis-result.schema.json",
            document_type="gate_2",
            enforce_stage_checklist=True,
        )
    except ValueError as exc:
        assert "stage_checklist must match the selected document type exactly" in str(exc)
        assert "gate2_gate3_commitments" in str(exc)
        return

    raise AssertionError("stage-specific checklist validator accepted a partial checklist")


def test_parse_and_validate_json_output_allows_custom_skill_schema_without_gate_checklist_enforcement():
    payload = _main_analysis_result_payload()
    payload["stage_checklist"] = payload["stage_checklist"][:1]

    parsed = schema_validation.parse_and_validate_json_output(
        structured_text=json.dumps(payload),
        schema_path="contracts/schemas/main-analysis-result.schema.json",
        document_type="gate_2",
    )

    assert [item["id"] for item in parsed["stage_checklist"]] == ["gate2_hypothesis_results"]


def _main_analysis_result_payload() -> dict:
    return {
        "verdict": "need_evidence",
        "summary": "Needs evidence.",
        "assessment_markdown": "Оценка документа\nРекомендация: запросить доказательства.",
        "stage_checklist": [
            {
                "id": "gate2_hypothesis_results",
                "label": "Результаты проверки гипотез из Gate 1",
                "status": "red",
                "evidence": "The document omits Gate 1 hypothesis results.",
            },
            {
                "id": "gate2_mvp_or_target_product",
                "label": "Описание MVP/целевого продукта",
                "status": "green",
                "evidence": "The document describes the target product.",
            },
            {
                "id": "gate2_mockups_or_user_flow",
                "label": "Mockups или видео пользовательского flow",
                "status": "red",
                "evidence": "The document omits user-flow mockups.",
            },
            {
                "id": "gate2_gate3_commitments",
                "label": "Commitments к Gate 3: сроки, expected performance, метрики",
                "status": "red",
                "evidence": "The document omits Gate 3 commitments.",
            },
        ],
        "findings": [],
        "checks": [],
        "layer_1_markdown": "Layer 1\nL1-001 - Decision-critical blocker.",
        "layer_1": [
            {
                "id": "L1-001",
                "severity": "critical",
                "issue": "Mandatory readiness is not proven.",
                "evidence": "The document does not close the required proof.",
            }
        ],
        "layer_2_markdown": "Layer 2\nL2-001 - Atomic weak-link finding.",
        "layer_2": [
            {
                "id": "L2-001",
                "parent_layer_1_id": "L1-001",
                "status": "fail",
                "severity": "high",
                "question": "Is the key target evidenced?",
                "answer": "NO",
                "issue": "A key target is not evidenced.",
                "evidence": "The document omits the proof.",
            }
        ],
    }

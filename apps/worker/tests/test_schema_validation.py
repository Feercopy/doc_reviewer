import json

from results import schema_validation


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

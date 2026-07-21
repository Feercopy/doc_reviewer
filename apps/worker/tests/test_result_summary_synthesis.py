from skills.result_summary_synthesis import (
    build_result_short_summary_prompt,
    extract_gate_challenger_recommendations,
    extract_ic_review_executive_summary,
)
from skills.result_rationale_synthesis import (
    build_result_rationale_prompt,
    extract_gate_challenger_rationale,
    extract_ic_review_text_list,
    extract_ic_review_top_findings,
)


def test_result_summary_synthesis_extracts_gate_recommendations_and_ic_executive_brief():
    gate_recommendations = extract_gate_challenger_recommendations(
        {
            "assessment_markdown": (
                "Оценка документа\n\n"
                "Рекомендация: не одобрять полный запуск до закрытия cohort evidence и unit economics.\n\n"
                "Почему: доказательств пока недостаточно."
            )
        }
    )
    ic_summary = extract_ic_review_executive_summary(
        {
            "run_mode": "ic_agentic_review_compact",
            "executive_brief": "IC recommends conditional approval only after model validation and risk mitigations.",
        }
    )

    prompt = build_result_short_summary_prompt(
        gate_recommendations=gate_recommendations or "",
        ic_executive_summary=ic_summary or "",
        output_language="ru",
        skill_prompt="Combine both source sections.",
        response_schema={"type": "object"},
    )

    assert gate_recommendations == "Рекомендация: не одобрять полный запуск до закрытия cohort evidence и unit economics."
    assert ic_summary == "IC recommends conditional approval only after model validation and risk mitigations."
    assert "Source 1 - Gate Challenger Recommendations" in prompt
    assert "Source 2 - IC Review Executive Summary" in prompt
    assert "Write in Russian." in prompt


def test_result_rationale_synthesis_extracts_gate_rationale_and_ic_findings():
    gate_rationale = extract_gate_challenger_rationale(
        {
            "assessment_markdown": (
                "Оценка документа\n\n"
                "Рекомендация: одобрять только ограниченный этап.\n\n"
                "Почему оценка именно такая:\n"
                "- В документе есть логика, но нет текущей A/B delta.\n"
                "- Масштабирование должно быть gated.\n\n"
                "Следующие шаги:\n"
                "- Запустить PoC."
            )
        }
    )
    ic_top_findings = extract_ic_review_top_findings(
        {
            "top_findings": [
                {
                    "title": "Model validation gap",
                    "severity": "critical",
                    "summary": "Financial model still depends on unvalidated uplift.",
                    "evidence": "Manual sheet contains formula blockers.",
                    "recommendation": "Reconcile formulas before approval.",
                }
            ],
            "critical_risks": ["Hiring scale-up may precede proof."],
            "data_gaps": ["No Avito A/B delta for current uplift."],
        }
    )
    critical_risks = extract_ic_review_text_list({"critical_risks": ["Hiring scale-up may precede proof."]}, "critical_risks")
    data_gaps = extract_ic_review_text_list({"data_gaps": ["No Avito A/B delta for current uplift."]}, "data_gaps")

    prompt = build_result_rationale_prompt(
        gate_rationale=gate_rationale or "",
        ic_top_findings=ic_top_findings or "",
        critical_risks=critical_risks,
        data_gaps=data_gaps,
        output_language="ru",
        skill_prompt="Combine rationale and top findings.",
        response_schema={"type": "object"},
    )

    assert gate_rationale == (
        "Почему оценка именно такая:\n"
        "- В документе есть логика, но нет текущей A/B delta.\n"
        "- Масштабирование должно быть gated."
    )
    assert "Model validation gap - critical" in (ic_top_findings or "")
    assert "Manual sheet contains formula blockers" in (ic_top_findings or "")
    assert critical_risks == ["Hiring scale-up may precede proof."]
    assert data_gaps == ["No Avito A/B delta for current uplift."]
    assert "Source 1 - Gate Challenger rationale" in prompt
    assert "Source 2 - IC Review Top findings" in prompt
    assert "For every rationale_items[] entry" in prompt
    assert "Write in Russian." in prompt

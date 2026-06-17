from benchmark.judge_prompt import build_judge_prompt


def test_build_judge_prompt_sends_only_expected_and_actual_layers():
    prompt = build_judge_prompt(
        etalon={
            "verdict": "need_evidence",
            "layer_1": [{"id": "L1-expected", "summary": "Expected L1"}],
            "layer_2": [{"id": "L2-expected", "finding": "Expected L2"}],
            "key_findings": ["must not be included"],
        },
        actual={
            "verdict": "reject",
            "summary": "Executive summary must not be included",
            "assessment_markdown": "Final synthesis must not be included",
            "layer_1": [{"id": "L1-actual", "issue": "Actual L1"}],
            "layer_2": [{"id": "L2-actual", "issue": "Actual L2"}],
            "layer_3": [{"id": "L3-actual", "issue": "Diagnostic only"}],
        },
        judge_prompt="LLM-as-a-judge для оценки v2",
    )

    assert "LLM-as-a-judge для оценки v2" in prompt
    assert "L1-expected" in prompt
    assert "L2-expected" in prompt
    assert "L1-actual" in prompt
    assert "L2-actual" in prompt
    assert "key_findings" not in prompt
    assert "Executive summary" not in prompt
    assert "Final synthesis" not in prompt
    assert "L3-actual" not in prompt

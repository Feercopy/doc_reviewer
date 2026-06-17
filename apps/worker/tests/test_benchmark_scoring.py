from benchmark.scoring import score_judge_layer, score_judge_output


def test_score_judge_layer_normal_case():
    score = score_judge_layer(
        expected_findings_count=4,
        actual_findings_count=5,
        exact_matches=[{"id": "m1"}, {"id": "m2"}],
        partial_matches=[{"id": "p1"}],
        missed_findings=[{"id": "miss1"}, {"id": "miss2"}],
        false_positives=[{"id": "fp1"}, {"id": "fp2"}, {"id": "fp3"}],
    )

    assert score["expected_findings_count"] == 4
    assert score["actual_findings_count"] == 5
    assert score["exact_matches_count"] == 2
    assert score["partial_matches_count"] == 1
    assert score["missed_findings_count"] == 2
    assert score["false_positives_count"] == 3
    assert score["precision"] == 0.4
    assert score["recall"] == 0.5
    assert round(score["f1"], 4) == 0.4444


def test_score_judge_layer_handles_empty_expected():
    score = score_judge_layer(
        expected_findings_count=0,
        actual_findings_count=2,
        exact_matches=[],
        partial_matches=[],
        missed_findings=[],
        false_positives=[{"id": "fp1"}, {"id": "fp2"}],
    )

    assert score["precision"] == 0
    assert score["recall"] == 0
    assert score["f1"] == 0


def test_score_judge_layer_handles_empty_actual():
    score = score_judge_layer(
        expected_findings_count=2,
        actual_findings_count=0,
        exact_matches=[],
        partial_matches=[],
        missed_findings=[{"id": "miss1"}, {"id": "miss2"}],
        false_positives=[],
    )

    assert score["precision"] == 0
    assert score["recall"] == 0
    assert score["f1"] == 0


def test_score_judge_layer_treats_both_empty_as_perfect():
    score = score_judge_layer(
        expected_findings_count=0,
        actual_findings_count=0,
        exact_matches=[],
        partial_matches=[],
        missed_findings=[],
        false_positives=[],
    )

    assert score["precision"] == 1
    assert score["recall"] == 1
    assert score["f1"] == 1


def test_score_judge_layer_does_not_count_partial_matches_as_exact():
    score = score_judge_layer(
        expected_findings_count=1,
        actual_findings_count=1,
        exact_matches=[],
        partial_matches=[{"id": "partial"}],
        missed_findings=[],
        false_positives=[],
    )

    assert score["partial_matches_count"] == 1
    assert score["precision"] == 0
    assert score["recall"] == 0
    assert score["f1"] == 0


def test_score_judge_output_v2_uses_partial_scores_and_micro_average():
    score = score_judge_output(
        expected={"layer_1": [{"id": "L1-1"}, {"id": "L1-2"}], "layer_2": [{"id": "L2-1"}] * 4},
        actual={"layer_1": [{"id": "A1"}, {"id": "A2"}, {"id": "A3"}], "layer_2": [{"id": "B1"}]},
        judge_output={
            "layer_1": {
                "n_ref": 2,
                "n_pred": 3,
                "score_sum": 1.5,
                "matched": [{"ref_id": "L1-1", "score": 1.0}, {"ref_id": "L1-2", "score": 0.5}],
                "missed_issues": [],
                "false_positives": [{"actual": "extra"}],
                "duplicates": [],
            },
            "layer_2": {
                "n_ref": 4,
                "n_pred": 1,
                "score_sum": 0.5,
                "matched": [{"ref_id": "L2-1", "score": 0.5}],
                "missed_issues": [{"ref_id": "L2-2"}, {"ref_id": "L2-3"}, {"ref_id": "L2-4"}],
                "false_positives": [],
                "duplicates": [],
            },
        },
    )

    assert score["layer_1"]["precision"] == 0.5
    assert score["layer_1"]["recall"] == 0.75
    assert round(score["layer_1"]["f1"], 4) == 0.6
    assert score["layer_2"]["precision"] == 0.5
    assert score["layer_2"]["recall"] == 0.125
    assert round(score["layer_2"]["f1"], 4) == 0.2
    assert score["precision"] == 0.5
    assert round(score["recall"], 4) == 0.3333
    assert round(score["f1"], 4) == 0.4


def test_score_judge_output_v2_normalizes_percentages_from_judge():
    score = score_judge_output(
        expected={"layer_1": [], "layer_2": []},
        actual={"layer_1": [], "layer_2": []},
        judge_output={
            "layer_1": {"n_ref": 1, "n_pred": 1, "score_sum": 0.75, "precision": 75, "recall": 75, "f1": 75},
            "layer_2": {"n_ref": 1, "n_pred": 1, "score_sum": 0.5, "precision": 50, "recall": 50, "f1": 50},
            "overall": {
                "n_ref_total": 2,
                "n_pred_total": 2,
                "score_sum_total": 1.25,
                "precision": 62.5,
                "recall": 62.5,
                "f1": 62.5,
            },
        },
    )

    assert score["layer_1"]["precision"] == 0.75
    assert score["layer_2"]["f1"] == 0.5
    assert score["precision"] == 0.625
    assert score["recall"] == 0.625
    assert score["f1"] == 0.625

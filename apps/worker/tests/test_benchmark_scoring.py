from benchmark.scoring import score_judge_layer


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

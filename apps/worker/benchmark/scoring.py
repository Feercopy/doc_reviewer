def score_judge_layer(
    *,
    expected_findings_count: int,
    actual_findings_count: int,
    exact_matches: list,
    partial_matches: list,
    missed_findings: list,
    false_positives: list,
) -> dict:
    exact_matches_count = len(exact_matches)
    if expected_findings_count == 0 and actual_findings_count == 0:
        precision = recall = f1 = 1
    else:
        precision = exact_matches_count / actual_findings_count if actual_findings_count else 0
        recall = exact_matches_count / expected_findings_count if expected_findings_count else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0

    return {
        "expected_findings_count": expected_findings_count,
        "actual_findings_count": actual_findings_count,
        "exact_matches_count": exact_matches_count,
        "partial_matches_count": len(partial_matches),
        "missed_findings_count": len(missed_findings),
        "false_positives_count": len(false_positives),
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def score_judge_output(*, expected: dict, actual: dict, judge_output: dict) -> dict:
    layer_1_judgement = judge_output.get("layer_1", {})
    layer_2_judgement = judge_output.get("layer_2", {})
    layer_1 = score_judge_layer(
        expected_findings_count=len(expected.get("layer_1", [])),
        actual_findings_count=len(actual.get("layer_1", [])),
        exact_matches=layer_1_judgement.get("exact_matches", []),
        partial_matches=layer_1_judgement.get("partial_matches", []),
        missed_findings=layer_1_judgement.get("missed_findings", []),
        false_positives=layer_1_judgement.get("false_positives", []),
    )
    layer_2 = score_judge_layer(
        expected_findings_count=len(expected.get("layer_2", [])),
        actual_findings_count=len(actual.get("layer_2", [])),
        exact_matches=layer_2_judgement.get("exact_matches", []),
        partial_matches=layer_2_judgement.get("partial_matches", []),
        missed_findings=layer_2_judgement.get("missed_findings", []),
        false_positives=layer_2_judgement.get("false_positives", []),
    )
    return {
        "layer_1": layer_1,
        "layer_2": layer_2,
        "precision": (layer_1["precision"] + layer_2["precision"]) / 2,
        "recall": (layer_1["recall"] + layer_2["recall"]) / 2,
        "f1": (layer_1["f1"] + layer_2["f1"]) / 2,
    }

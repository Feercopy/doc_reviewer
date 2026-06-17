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
    if _is_v2_judge_output(judge_output):
        return _score_v2_judge_output(judge_output)

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


def _is_v2_judge_output(judge_output: dict) -> bool:
    layer_1 = judge_output.get("layer_1")
    layer_2 = judge_output.get("layer_2")
    return isinstance(layer_1, dict) and isinstance(layer_2, dict) and (
        "score_sum" in layer_1 or "n_ref" in layer_1 or "score_sum" in layer_2 or "n_ref" in layer_2
    )


def _score_v2_judge_output(judge_output: dict) -> dict:
    layer_1 = _score_v2_layer(judge_output.get("layer_1", {}))
    layer_2 = _score_v2_layer(judge_output.get("layer_2", {}))
    overall = judge_output.get("overall") if isinstance(judge_output.get("overall"), dict) else None
    if overall:
        precision = _metric_value(overall.get("precision"))
        recall = _metric_value(overall.get("recall"))
        f1 = _metric_value(overall.get("f1"))
        score_sum_total = _number(overall.get("score_sum_total"))
        n_ref_total = int(_number(overall.get("n_ref_total")))
        n_pred_total = int(_number(overall.get("n_pred_total")))
    else:
        score_sum_total = layer_1["score_sum"] + layer_2["score_sum"]
        n_ref_total = layer_1["n_ref"] + layer_2["n_ref"]
        n_pred_total = layer_1["n_pred"] + layer_2["n_pred"]
        precision = score_sum_total / n_pred_total if n_pred_total else 0
        recall = score_sum_total / n_ref_total if n_ref_total else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0

    return {
        "layer_1": layer_1,
        "layer_2": layer_2,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "score_sum_total": score_sum_total,
        "n_ref_total": n_ref_total,
        "n_pred_total": n_pred_total,
    }


def _score_v2_layer(layer: dict) -> dict:
    n_ref = int(_number(layer.get("n_ref")))
    n_pred = int(_number(layer.get("n_pred")))
    score_sum = _number(layer.get("score_sum"))
    precision = _metric_value(layer.get("precision"))
    recall = _metric_value(layer.get("recall"))
    f1 = _metric_value(layer.get("f1"))
    if "precision" not in layer:
        precision = score_sum / n_pred if n_pred else 0
    if "recall" not in layer:
        recall = score_sum / n_ref if n_ref else 0
    if "f1" not in layer:
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    return {
        "expected_findings_count": n_ref,
        "actual_findings_count": n_pred,
        "exact_matches_count": sum(1 for item in layer.get("matched", []) if _number(item.get("score")) == 1),
        "partial_matches_count": sum(1 for item in layer.get("matched", []) if 0 < _number(item.get("score")) < 1),
        "missed_findings_count": len(layer.get("missed_issues", [])),
        "false_positives_count": len(layer.get("false_positives", [])),
        "duplicate_count": len(layer.get("duplicates", [])),
        "score_sum": score_sum,
        "n_ref": n_ref,
        "n_pred": n_pred,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _metric_value(value: object) -> float:
    number = _number(value)
    return number / 100 if number > 1 else number


def _number(value: object) -> float:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except ValueError:
            return 0
    return 0

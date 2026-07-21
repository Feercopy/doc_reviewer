def build_benchmark_report(*, benchmark_name: str, document_results: list[dict], aggregate: dict) -> dict:
    failures = [item for item in document_results if item.get("status") == "failed"]
    return {
        "title": benchmark_name,
        "overall": aggregate,
        "documents": document_results,
        "model_failures": failures,
        "missed_findings": aggregate.get("missed_findings", []),
        "false_positives": aggregate.get("false_positives", []),
        "partial_matches": aggregate.get("partial_matches", []),
        "recommendations": _collect_recommendations(document_results),
    }


def _collect_recommendations(document_results: list[dict]) -> list:
    recommendations = []
    for result in document_results:
        judge_output = result.get("judge_output") or {}
        recommendations.extend(judge_output.get("recommendations", []))
    return recommendations

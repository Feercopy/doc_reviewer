import json


def build_judge_prompt(*, etalon: dict, actual: dict, judge_prompt: str) -> str:
    expected_layers = _layer_only_payload(etalon)
    actual_layers = _layer_only_payload(actual)
    return "\n\n".join(
        [
            judge_prompt,
            "Compare only the expected and actual verdict, Layer 1, and Layer 2. Return only JSON matching the schema.",
            "Expected etalon Layer 1 / Layer 2:",
            json.dumps(expected_layers, ensure_ascii=False, sort_keys=True),
            "Actual Gate Challenger Layer 1 / Layer 2:",
            json.dumps(actual_layers, ensure_ascii=False, sort_keys=True),
        ]
    )


def _layer_only_payload(value: dict) -> dict:
    return {
        "verdict": value.get("verdict"),
        "layer_1": value.get("layer_1") if isinstance(value.get("layer_1"), list) else [],
        "layer_2": value.get("layer_2") if isinstance(value.get("layer_2"), list) else [],
    }

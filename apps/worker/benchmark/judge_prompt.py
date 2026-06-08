import json


def build_judge_prompt(*, etalon: dict, actual: dict, judge_prompt: str) -> str:
    return "\n\n".join(
        [
            judge_prompt,
            "Compare the actual analysis output to the expected etalon. Return only JSON matching the schema.",
            "Expected etalon:",
            json.dumps(etalon, ensure_ascii=False, sort_keys=True),
            "Actual analysis output:",
            json.dumps(actual, ensure_ascii=False, sort_keys=True),
        ]
    )

from typing import Any


DEFAULT_OUTPUT_LANGUAGE = "ru"
SUPPORTED_OUTPUT_LANGUAGES = {"ru", "en"}


def normalize_output_language(output_language: Any) -> str:
    if isinstance(output_language, str):
        normalized = output_language.strip().lower()
        if normalized in SUPPORTED_OUTPUT_LANGUAGES:
            return normalized
    return DEFAULT_OUTPUT_LANGUAGE


def output_language_instruction(output_language: Any) -> str:
    language = normalize_output_language(output_language)
    if language == "en":
        return "\n".join(
            [
                "Output language requirement:",
                "Write all reader-facing fields in English only. Do not switch to Russian even if the source "
                "document contains Russian text. Quote source text only when necessary; otherwise translate or "
                "summarize evidence in English.",
            ]
        )

    return "\n".join(
        [
            "Output language requirement:",
            "Write all reader-facing fields in Russian only. Do not switch to English except for source quotes, "
            "names, metrics, and stable terminology.",
        ]
    )

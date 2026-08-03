from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from parsers.anonymizer import (
    SANITIZER_VERSION,
    PersonalDataAnonymizer,
    config_hash,
    deanonymize_value,
)


RUN_PARAMETER_KEY = "model_anonymization"


@dataclass(frozen=True)
class PromptAnonymization:
    prompt: str
    metadata: dict[str, Any]


def anonymize_prompt_for_model(prompt: str, *, existing_metadata: dict[str, Any] | None = None) -> PromptAnonymization:
    if not get_settings().document_anonymization_enabled:
        return PromptAnonymization(prompt=prompt, metadata={"enabled": False})

    seed_replacements = _metadata_replacements(existing_metadata)
    anonymizer = PersonalDataAnonymizer(replacements=seed_replacements)
    anonymized_prompt = anonymizer.anonymize_text(prompt)
    replacements = anonymizer.replacements()
    report = anonymizer.report().to_dict()
    return PromptAnonymization(
        prompt=anonymized_prompt,
        metadata={
            "enabled": True,
            "strategy": "strict_local_pii_rules",
            "version": SANITIZER_VERSION,
            "config_hash": config_hash(),
            "replacement_count": len(replacements),
            "replacements": replacements,
            "report": report,
        },
    )


def deanonymize_model_value(value: Any, *, metadata: dict[str, Any] | None) -> Any:
    replacements = _metadata_replacements(metadata)
    if not replacements:
        return value
    return deanonymize_value(value, replacements)


def deanonymize_model_text(text: str, *, metadata: dict[str, Any] | None) -> str:
    value = deanonymize_model_value(text, metadata=metadata)
    return value if isinstance(value, str) else text


def _metadata_replacements(metadata: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(metadata, dict):
        return []
    replacements = metadata.get("replacements")
    if not isinstance(replacements, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in replacements:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        placeholder = item.get("placeholder")
        value = item.get("value")
        if isinstance(kind, str) and isinstance(placeholder, str) and isinstance(value, str):
            normalized.append({"kind": kind, "placeholder": placeholder, "value": value})
    return normalized

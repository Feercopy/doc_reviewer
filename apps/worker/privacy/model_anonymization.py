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
PROVIDER_RUN_PARAMETER_ALLOWLIST = {
    "connect_timeout_seconds",
    "json_schema_strict",
    "max_output_tokens",
    "max_retries",
    "mock_provider_response_result",
    "mock_provider_result",
    "response_format",
    "temperature",
    "text_format",
    "timeout_seconds",
}


@dataclass(frozen=True)
class PromptAnonymization:
    prompt: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ContextAnonymization:
    value: Any
    metadata: dict[str, Any]


def anonymize_prompt_for_model(
    prompt: str,
    *,
    existing_metadata: dict[str, Any] | None = None,
) -> PromptAnonymization:
    if not get_settings().document_anonymization_enabled:
        return PromptAnonymization(prompt=prompt, metadata={"enabled": False})

    anonymizer = _anonymizer(existing_metadata)
    anonymized_prompt = anonymizer.anonymize_text(prompt)
    return PromptAnonymization(
        prompt=anonymized_prompt,
        metadata=_metadata(anonymizer, scope="full_prompt"),
    )


def anonymize_prompt_sections_for_model(
    prompt: str,
    *,
    sections: list[tuple[str, str | None]],
    existing_metadata: dict[str, Any] | None = None,
) -> PromptAnonymization:
    if not get_settings().document_anonymization_enabled:
        return PromptAnonymization(prompt=prompt, metadata={"enabled": False})

    anonymizer = _anonymizer(existing_metadata)
    anonymized_prompt = _anonymize_sections(prompt, sections=sections, anonymizer=anonymizer)
    return PromptAnonymization(
        prompt=anonymized_prompt,
        metadata=_metadata(anonymizer, scope="selected_prompt_sections"),
    )


def anonymize_value_for_model(
    value: Any,
    *,
    existing_metadata: dict[str, Any] | None = None,
) -> ContextAnonymization:
    if not get_settings().document_anonymization_enabled:
        return ContextAnonymization(value=value, metadata={"enabled": False})

    anonymizer = _anonymizer(existing_metadata)
    return ContextAnonymization(
        value=anonymizer.anonymize_value(value),
        metadata=_metadata(anonymizer, scope="structured_context"),
    )


def deanonymize_model_value(value: Any, *, metadata: dict[str, Any] | None) -> Any:
    replacements = _metadata_replacements(metadata)
    if not replacements:
        return value
    return deanonymize_value(value, replacements)


def deanonymize_model_text(text: str, *, metadata: dict[str, Any] | None) -> str:
    value = deanonymize_model_value(text, metadata=metadata)
    return value if isinstance(value, str) else text


def provider_safe_run_parameters(run_parameters: dict[str, Any] | None) -> dict[str, Any]:
    parameters = run_parameters or {}
    return {key: parameters[key] for key in PROVIDER_RUN_PARAMETER_ALLOWLIST if key in parameters}


def db_safe_anonymization_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if metadata is None:
        return None
    sanitized = _strip_postgres_unsafe_text(metadata)
    return sanitized if isinstance(sanitized, dict) else None


def _anonymizer(existing_metadata: dict[str, Any] | None) -> PersonalDataAnonymizer:
    return PersonalDataAnonymizer(replacements=_metadata_replacements(existing_metadata))


def _metadata(anonymizer: PersonalDataAnonymizer, *, scope: str) -> dict[str, Any]:
    replacements = anonymizer.replacements()
    report = anonymizer.report().to_dict()
    return {
        "enabled": True,
        "strategy": "strict_local_pii_rules",
        "version": SANITIZER_VERSION,
        "config_hash": config_hash(),
        "scope": scope,
        "replacement_count": len(replacements),
        "replacements": replacements,
        "report": report,
    }


def _anonymize_sections(
    prompt: str,
    *,
    sections: list[tuple[str, str | None]],
    anonymizer: PersonalDataAnonymizer,
) -> str:
    result = prompt
    for start_marker, end_marker in sections:
        result = _anonymize_section(
            result,
            start_marker=start_marker,
            end_marker=end_marker,
            anonymizer=anonymizer,
        )
    return result


def _anonymize_section(
    prompt: str,
    *,
    start_marker: str,
    end_marker: str | None,
    anonymizer: PersonalDataAnonymizer,
) -> str:
    start = prompt.find(start_marker)
    if start < 0:
        return prompt
    content_start = start + len(start_marker)
    end = prompt.find(end_marker, content_start) if end_marker else -1
    content_end = end if end >= 0 else len(prompt)
    content = prompt[content_start:content_end]
    anonymized_content = anonymizer.anonymize_text(content)
    return prompt[:content_start] + anonymized_content + prompt[content_end:]


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


def _strip_postgres_unsafe_text(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_strip_postgres_unsafe_text(item) for item in value]
    if isinstance(value, dict):
        return {
            _strip_postgres_unsafe_text(key): _strip_postgres_unsafe_text(item)
            for key, item in value.items()
        }
    return value

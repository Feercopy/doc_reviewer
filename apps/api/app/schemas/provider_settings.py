from pydantic import BaseModel, field_validator, model_validator

from app.schemas.enums import Provider


DEFAULT_OPENAI_COMPATIBLE_MODELS = [
    "anthropic/claude-opus-4.7",
    "anthropic/claude-sonnet-4.6",
    "deepseek/deepseek-v4-pro",
    "google/gemini-3.5-flash",
    "openai/gpt-5.5",
    "qwen/qwen3.5-397b-a17b",
]


class ProviderKeyUpsert(BaseModel):
    api_key: str
    base_url: str | None = None
    default_model: str
    available_models: list[str] | None = None

    @field_validator("default_model")
    @classmethod
    def default_model_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Default model is required")
        return stripped

    @field_validator("available_models")
    @classmethod
    def available_models_must_not_contain_blanks(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        models = _normalize_models(value)
        if not models:
            raise ValueError("At least one model is required")
        return models

    @model_validator(mode="after")
    def default_model_must_be_available(self) -> "ProviderKeyUpsert":
        if self.available_models is not None and self.default_model not in self.available_models:
            raise ValueError("Default model must be included in available models")
        return self


class ProviderKeyModelSettingsUpdate(BaseModel):
    default_model: str
    available_models: list[str]

    @field_validator("default_model")
    @classmethod
    def default_model_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Default model is required")
        return stripped

    @field_validator("available_models")
    @classmethod
    def available_models_must_not_contain_blanks(cls, value: list[str]) -> list[str]:
        models = _normalize_models(value)
        if not models:
            raise ValueError("At least one model is required")
        return models

    @model_validator(mode="after")
    def default_model_must_be_available(self) -> "ProviderKeyModelSettingsUpdate":
        if self.default_model not in self.available_models:
            raise ValueError("Default model must be included in available models")
        return self


class ProviderKeyRead(BaseModel):
    provider: Provider
    base_url: str | None
    default_model: str
    available_models: list[str]
    api_key_fingerprint: str
    has_key: bool


class ProviderKeysListResponse(BaseModel):
    provider_keys: list[ProviderKeyRead]


class ProviderModelOptionsRead(BaseModel):
    provider: Provider
    default_model: str
    available_models: list[str]
    has_key: bool


class ProviderModelOptionsListResponse(BaseModel):
    provider_models: list[ProviderModelOptionsRead]


class ProviderKeyTestResponse(BaseModel):
    provider: Provider
    status: str
    message: str
    default_model: str | None
    base_url: str | None


def default_available_models(provider: Provider, default_model: str | None = None) -> list[str]:
    if provider == Provider.OPENAI_COMPATIBLE:
        return list(DEFAULT_OPENAI_COMPATIBLE_MODELS)
    return [default_model] if default_model else []


def normalize_available_models(provider: Provider, models: list[str] | None, default_model: str) -> list[str]:
    normalized = _normalize_models(models or default_available_models(provider, default_model))
    if default_model not in normalized:
        normalized.insert(0, default_model)
    return normalized


def _normalize_models(models: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in models:
        model = item.strip()
        if not model or model in seen:
            continue
        normalized.append(model)
        seen.add(model)
    return normalized

from pydantic import BaseModel

from app.schemas.enums import Provider


class ProviderKeyUpsert(BaseModel):
    api_key: str
    base_url: str | None = None
    default_model: str


class ProviderKeyRead(BaseModel):
    provider: Provider
    base_url: str | None
    default_model: str
    api_key_fingerprint: str
    has_key: bool


class ProviderKeysListResponse(BaseModel):
    provider_keys: list[ProviderKeyRead]


class ProviderKeyTestResponse(BaseModel):
    provider: Provider
    status: str
    message: str
    default_model: str | None
    base_url: str | None

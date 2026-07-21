from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.enums import Provider


class ProviderRunRequest(BaseModel):
    provider: Provider
    model: str
    api_key: str | None = None
    base_url: str | None = None
    prompt: str
    response_schema: dict
    run_parameters: dict = Field(default_factory=dict)


class ProviderResponseRequest(BaseModel):
    provider: Provider
    model: str
    api_key: str | None = None
    base_url: str | None = None
    input: str
    response_schema: dict
    run_parameters: dict = Field(default_factory=dict)
    previous_response_id: str | None = None
    background: bool = False


class AnalysisProviderResult(BaseModel):
    structured_text: str
    raw_output: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int
    estimated_cost: Decimal | None = None
    provider_metadata: dict = Field(default_factory=dict)


class ProviderAdapter:
    def run(self, request: ProviderRunRequest) -> AnalysisProviderResult:
        raise NotImplementedError

    def run_response(self, request: ProviderResponseRequest) -> AnalysisProviderResult:
        raise NotImplementedError

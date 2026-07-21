from app.schemas.enums import Provider
from providers.base import AnalysisProviderResult, ProviderAdapter, ProviderResponseRequest, ProviderRunRequest
from providers.anthropic_compatible import AnthropicCompatibleAdapter
from providers.hermes import HermesAdapter
from providers.openai_compatible import OpenAICompatibleAdapter
from app.logging import provider_logger


class MockProviderAdapter(ProviderAdapter):
    def run(self, request: ProviderRunRequest) -> AnalysisProviderResult:
        result = request.run_parameters.get("mock_provider_result")
        if not result:
            raise RuntimeError("mock_provider_result is required for local test provider execution")
        return AnalysisProviderResult(**result)

    def run_response(self, request: ProviderResponseRequest) -> AnalysisProviderResult:
        result = request.run_parameters.get("mock_provider_response_result")
        if not result:
            raise RuntimeError("mock_provider_response_result is required for local test provider execution")
        return AnalysisProviderResult(**result)


def get_provider_adapter(provider: Provider, run_parameters: dict | None = None) -> ProviderAdapter:
    if run_parameters and ("mock_provider_result" in run_parameters or "mock_provider_response_result" in run_parameters):
        return LoggingProviderAdapter(MockProviderAdapter())
    if provider == Provider.OPENAI_COMPATIBLE:
        return LoggingProviderAdapter(OpenAICompatibleAdapter())
    if provider == Provider.ANTHROPIC_COMPATIBLE:
        return LoggingProviderAdapter(AnthropicCompatibleAdapter())
    if provider == Provider.HERMES:
        return LoggingProviderAdapter(HermesAdapter())
    raise RuntimeError(f"unsupported_provider:{provider}")


class LoggingProviderAdapter(ProviderAdapter):
    def __init__(self, wrapped: ProviderAdapter) -> None:
        self._wrapped = wrapped

    def run(self, request: ProviderRunRequest) -> AnalysisProviderResult:
        try:
            result = self._wrapped.run(request)
        except Exception as exc:
            provider_logger.info(
                "provider_failed",
                extra={
                    "provider": request.provider.value,
                    "model": request.model,
                    "latency_ms": None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "error_class": exc.__class__.__name__,
                },
            )
            raise
        provider_logger.info(
            "provider_completed",
            extra={
                "provider": request.provider.value,
                "model": request.model,
                "latency_ms": result.latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "error_class": None,
            },
        )
        return result

    def run_response(self, request: ProviderResponseRequest) -> AnalysisProviderResult:
        try:
            result = self._wrapped.run_response(request)
        except Exception as exc:
            provider_logger.info(
                "provider_failed",
                extra={
                    "provider": request.provider.value,
                    "model": request.model,
                    "latency_ms": None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "error_class": exc.__class__.__name__,
                },
            )
            raise
        provider_logger.info(
            "provider_completed",
            extra={
                "provider": request.provider.value,
                "model": request.model,
                "latency_ms": result.latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "error_class": None,
            },
        )
        return result

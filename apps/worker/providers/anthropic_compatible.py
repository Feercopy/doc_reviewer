import time
from collections.abc import Callable

from providers.base import AnalysisProviderResult, ProviderAdapter, ProviderRunRequest
from providers.proxy import outbound_proxy_kwargs


class AnthropicCompatibleAdapter(ProviderAdapter):
    def __init__(self, client_factory: Callable[..., object] | None = None) -> None:
        self._client_factory = client_factory or self._default_client_factory

    def run(self, request: ProviderRunRequest) -> AnalysisProviderResult:
        if not request.api_key:
            raise RuntimeError("provider_key_missing")

        client = self._client_factory(api_key=request.api_key, base_url=request.base_url)
        kwargs = {
            "model": request.model,
            "max_tokens": request.run_parameters.get("max_output_tokens", 6000),
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if "temperature" in request.run_parameters:
            kwargs["temperature"] = request.run_parameters["temperature"]

        started = time.monotonic()
        response = client.messages.create(**kwargs)
        latency_ms = int((time.monotonic() - started) * 1000)
        usage = getattr(response, "usage", None)

        return AnalysisProviderResult(
            structured_text=_extract_text(response),
            raw_output=_dump_response(response),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            latency_ms=latency_ms,
            provider_metadata={"provider": request.provider.value},
        )

    @staticmethod
    def _default_client_factory(*, api_key: str, base_url: str | None) -> object:
        from anthropic import Anthropic, DefaultHttpxClient

        kwargs: dict[str, object] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        proxy_kwargs = outbound_proxy_kwargs(base_url)
        if proxy_kwargs:
            kwargs["http_client"] = DefaultHttpxClient(**proxy_kwargs)
        return Anthropic(**kwargs)


def _extract_text(response: object) -> str:
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _dump_response(response: object) -> str:
    if hasattr(response, "model_dump_json"):
        return response.model_dump_json()
    return str(response)

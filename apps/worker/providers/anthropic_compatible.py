import time
from collections.abc import Callable

from providers.base import AnalysisProviderResult, ProviderAdapter, ProviderRunRequest
from providers.proxy import outbound_proxy_kwargs


class AnthropicCompatibleAdapter(ProviderAdapter):
    def __init__(self, client_factory: Callable[..., object] | None = None) -> None:
        self._client_factory = client_factory or self._default_client_factory

    def is_retryable_transport_error(self, exc: BaseException) -> bool:
        from anthropic import APIConnectionError, APITimeoutError

        return isinstance(exc, APIConnectionError) and not isinstance(exc, APITimeoutError)

    def run(self, request: ProviderRunRequest) -> AnalysisProviderResult:
        if not request.api_key:
            raise RuntimeError("provider_key_missing")

        capture_http_metadata = request.run_parameters.get("capture_http_metadata") is True
        client_kwargs = {"api_key": request.api_key, "base_url": request.base_url}
        if capture_http_metadata:
            client_kwargs.update({
                "max_retries": request.run_parameters.get("max_retries"),
                "timeout_seconds": request.run_parameters.get("timeout_seconds"),
                "connect_timeout_seconds": request.run_parameters.get("connect_timeout_seconds"),
            })
        client = self._client_factory(**client_kwargs)
        kwargs = {
            "model": request.model,
            "max_tokens": request.run_parameters.get("max_output_tokens", 6000),
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if "temperature" in request.run_parameters:
            kwargs["temperature"] = request.run_parameters["temperature"]

        started = time.monotonic()
        raw_response = None
        if capture_http_metadata:
            raw_response = client.messages.with_raw_response.create(**kwargs)
            response = raw_response.parse()
        else:
            response = client.messages.create(**kwargs)
        latency_ms = int((time.monotonic() - started) * 1000)
        usage = getattr(response, "usage", None)
        metadata = {"provider": request.provider.value, "stop_reason": getattr(response, "stop_reason", None)}
        if raw_response is not None:
            metadata.update({
                "request_id": raw_response.headers.get("x-request-id"),
                "response_id": getattr(response, "id", None),
                "response_status": raw_response.status_code,
            })

        return AnalysisProviderResult(
            structured_text=_extract_text(response),
            raw_output=_dump_response(response),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            latency_ms=latency_ms,
            provider_metadata=metadata,
        )

    @staticmethod
    def _default_client_factory(
        *, api_key: str, base_url: str | None, max_retries: int | None = None,
        timeout_seconds: float | None = None, connect_timeout_seconds: float | None = None,
    ) -> object:
        from anthropic import Anthropic, DefaultHttpxClient, Timeout

        kwargs: dict[str, object] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        if type(max_retries) is int and max_retries >= 0:
            kwargs["max_retries"] = max_retries
        if type(timeout_seconds) in (int, float) and timeout_seconds > 0:
            connect = connect_timeout_seconds if type(connect_timeout_seconds) in (int, float) and connect_timeout_seconds > 0 else min(timeout_seconds, 30)
            kwargs["timeout"] = Timeout(timeout_seconds, connect=connect)
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

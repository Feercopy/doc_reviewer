import time
from collections.abc import Callable

from providers.base import AnalysisProviderResult, ProviderAdapter, ProviderRunRequest
from providers.proxy import outbound_proxy_kwargs


class OpenAICompatibleAdapter(ProviderAdapter):
    def __init__(self, client_factory: Callable[..., object] | None = None) -> None:
        self._client_factory = client_factory or self._default_client_factory

    def run(self, request: ProviderRunRequest) -> AnalysisProviderResult:
        if not request.api_key:
            raise RuntimeError("provider_key_missing")

        client = self._client_factory(api_key=request.api_key, base_url=request.base_url)
        response_format = request.run_parameters.get("response_format") or {
            "type": "json_schema",
            "json_schema": {
                "name": "analysis_result",
                "schema": request.response_schema,
                "strict": bool(request.run_parameters.get("json_schema_strict", False)),
            },
        }
        kwargs = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "response_format": response_format,
        }
        if "temperature" in request.run_parameters:
            kwargs["temperature"] = request.run_parameters["temperature"]
        if "max_output_tokens" in request.run_parameters:
            kwargs["max_tokens"] = request.run_parameters["max_output_tokens"]

        started = time.monotonic()
        response = client.chat.completions.create(**kwargs)
        latency_ms = int((time.monotonic() - started) * 1000)

        choice = response.choices[0]
        structured_text = choice.message.content or ""
        usage = getattr(response, "usage", None)
        return AnalysisProviderResult(
            structured_text=structured_text,
            raw_output=_dump_response(response),
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            latency_ms=latency_ms,
            provider_metadata={"provider": request.provider.value},
        )

    @staticmethod
    def _default_client_factory(*, api_key: str, base_url: str | None) -> object:
        from openai import DefaultHttpxClient, OpenAI

        kwargs: dict[str, object] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        proxy_kwargs = outbound_proxy_kwargs(base_url)
        if proxy_kwargs:
            kwargs["http_client"] = DefaultHttpxClient(**proxy_kwargs)
        return OpenAI(**kwargs)


def _dump_response(response: object) -> str:
    if hasattr(response, "model_dump_json"):
        return response.model_dump_json()
    return str(response)

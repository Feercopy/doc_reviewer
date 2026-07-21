import time
from collections.abc import Callable
from copy import deepcopy
from typing import Any

import httpx

from providers.base import AnalysisProviderResult, ProviderAdapter, ProviderResponseRequest, ProviderRunRequest
from providers.proxy import outbound_proxy_kwargs


class OpenAICompatibleAdapter(ProviderAdapter):
    def __init__(self, client_factory: Callable[..., object] | None = None) -> None:
        self._client_factory = client_factory or self._default_client_factory

    def run(self, request: ProviderRunRequest) -> AnalysisProviderResult:
        if not request.api_key:
            raise RuntimeError("provider_key_missing")

        client = self._client_factory(
            api_key=request.api_key,
            base_url=request.base_url,
            timeout_seconds=_positive_float(request.run_parameters.get("timeout_seconds")),
            connect_timeout_seconds=_positive_float(request.run_parameters.get("connect_timeout_seconds")),
            max_retries=_positive_int(request.run_parameters.get("max_retries")),
        )
        response_format = request.run_parameters.get("response_format") or {
            "type": "json_schema",
            "json_schema": {
                "name": "analysis_result",
                "schema": _provider_compatible_schema(request.response_schema),
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

    def run_response(self, request: ProviderResponseRequest) -> AnalysisProviderResult:
        if not request.api_key:
            raise RuntimeError("provider_key_missing")

        client = self._client_factory(
            api_key=request.api_key,
            base_url=request.base_url,
            timeout_seconds=_positive_float(request.run_parameters.get("timeout_seconds")),
            connect_timeout_seconds=_positive_float(request.run_parameters.get("connect_timeout_seconds")),
            max_retries=_positive_int(request.run_parameters.get("max_retries")),
        )
        text_format = request.run_parameters.get("text_format") or {
            "format": {
                "type": "json_schema",
                "name": "analysis_result",
                "schema": _provider_compatible_schema(request.response_schema),
                "strict": bool(request.run_parameters.get("json_schema_strict", False)),
            }
        }
        kwargs = {
            "model": request.model,
            "input": request.input,
            "text": text_format,
        }
        if request.previous_response_id:
            kwargs["previous_response_id"] = request.previous_response_id
        if request.background:
            kwargs["background"] = True
        if "temperature" in request.run_parameters:
            kwargs["temperature"] = request.run_parameters["temperature"]
        if "max_output_tokens" in request.run_parameters:
            kwargs["max_output_tokens"] = request.run_parameters["max_output_tokens"]

        started = time.monotonic()
        response = client.responses.create(**kwargs)
        latency_ms = int((time.monotonic() - started) * 1000)

        usage = getattr(response, "usage", None)
        response_id = getattr(response, "id", None)
        return AnalysisProviderResult(
            structured_text=_responses_text(response),
            raw_output=_dump_response(response),
            input_tokens=_usage_value(usage, "input_tokens", "prompt_tokens"),
            output_tokens=_usage_value(usage, "output_tokens", "completion_tokens"),
            latency_ms=latency_ms,
            provider_metadata={"provider": request.provider.value, "response_id": response_id},
        )

    @staticmethod
    def _default_client_factory(
        *,
        api_key: str,
        base_url: str | None,
        timeout_seconds: float | None = None,
        connect_timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> object:
        from openai import DefaultHttpxClient, OpenAI

        kwargs: dict[str, object] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        timeout = _httpx_timeout(timeout_seconds=timeout_seconds, connect_timeout_seconds=connect_timeout_seconds)
        if timeout is not None:
            kwargs["timeout"] = timeout
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        proxy_kwargs = outbound_proxy_kwargs(base_url)
        if proxy_kwargs:
            http_client_kwargs = dict(proxy_kwargs)
            if timeout is not None:
                http_client_kwargs["timeout"] = timeout
            kwargs["http_client"] = DefaultHttpxClient(**http_client_kwargs)
        return OpenAI(**kwargs)


def _dump_response(response: object) -> str:
    if hasattr(response, "model_dump_json"):
        return response.model_dump_json()
    return str(response)


def _responses_text(response: object) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)

    output = getattr(response, "output", None)
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        content = getattr(item, "content", None)
        if not isinstance(content, list):
            continue
        for content_item in content:
            text = getattr(content_item, "text", None)
            if text:
                parts.append(str(text))
    return "\n".join(parts)


def _usage_value(usage: object | None, *names: str) -> int | None:
    if usage is None:
        return None
    for name in names:
        value = getattr(usage, name, None)
        if value is not None:
            return int(value)
    return None


def _positive_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _positive_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _httpx_timeout(*, timeout_seconds: float | None, connect_timeout_seconds: float | None) -> httpx.Timeout | None:
    if timeout_seconds is None:
        return None
    connect_timeout = connect_timeout_seconds if connect_timeout_seconds is not None else min(timeout_seconds, 30.0)
    return httpx.Timeout(timeout_seconds, connect=connect_timeout)


def _provider_compatible_schema(schema: dict[str, Any]) -> dict[str, Any]:
    compatible = deepcopy(schema)
    _remove_provider_unsupported_constraints(compatible)
    return compatible


def _remove_provider_unsupported_constraints(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "array" and isinstance(node.get("minItems"), int) and node["minItems"] > 1:
            node.pop("minItems", None)
        if node.get("type") == "array":
            node.pop("maxItems", None)
        if node.get("type") in {"number", "integer"}:
            node.pop("minimum", None)
            node.pop("maximum", None)
            node.pop("exclusiveMinimum", None)
            node.pop("exclusiveMaximum", None)
        for value in node.values():
            _remove_provider_unsupported_constraints(value)
    elif isinstance(node, list):
        for item in node:
            _remove_provider_unsupported_constraints(item)

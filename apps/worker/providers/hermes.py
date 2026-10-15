import json
import time
from collections.abc import Callable

import httpx

from app.core.config import get_settings
from providers.base import AnalysisProviderResult, ProviderAdapter, ProviderRunRequest
from providers.proxy import outbound_proxy_kwargs


class HermesAdapter(ProviderAdapter):
    def __init__(self, post: Callable[..., object] | None = None) -> None:
        self._post = post

    def is_retryable_transport_error(self, exc: BaseException) -> bool:
        return isinstance(exc, httpx.TransportError) and not isinstance(exc, httpx.TimeoutException)

    def run(self, request: ProviderRunRequest) -> AnalysisProviderResult:
        settings = get_settings()
        if not settings.hermes_enabled:
            raise RuntimeError("provider_unavailable")

        url = (request.base_url or settings.hermes_http_url).rstrip("/") + "/v1/analysis"
        headers: dict[str, str] = {}
        if request.api_key:
            headers["Authorization"] = f"Bearer {request.api_key}"
        payload = {
            "model": request.model,
            "prompt": request.prompt,
            "response_schema": request.response_schema,
            "run_parameters": {key: value for key, value in request.run_parameters.items() if key != "capture_http_metadata"},
        }

        started = time.monotonic()
        if self._post:
            response = self._post(url, json=payload, headers=headers)
        else:
            timeout = request.run_parameters.get("timeout_seconds", 60)
            client_kwargs: dict[str, object] = {"timeout": timeout}
            client_kwargs.update(outbound_proxy_kwargs(url))
            with httpx.Client(**client_kwargs) as client:
                response = client.post(url, json=payload, headers=headers)
        latency_ms = int((time.monotonic() - started) * 1000)
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        supplied_metadata = data.get("provider_metadata")
        metadata = supplied_metadata if isinstance(supplied_metadata, dict) and supplied_metadata else {"provider": request.provider.value}
        if request.run_parameters.get("capture_http_metadata") is True:
            metadata = {
                **metadata,
                "request_id": response.headers.get("x-request-id"),
                "response_id": data.get("id"),
                "response_status": response.status_code,
            }

        return AnalysisProviderResult(
            structured_text=data.get("structured_text") or data.get("content") or data.get("output") or "",
            raw_output=json.dumps(data, ensure_ascii=False, sort_keys=True),
            input_tokens=usage.get("input_tokens") or usage.get("prompt_tokens"),
            output_tokens=usage.get("output_tokens") or usage.get("completion_tokens"),
            latency_ms=data.get("latency_ms") or latency_ms,
            estimated_cost=data.get("estimated_cost"),
            provider_metadata=metadata,
        )

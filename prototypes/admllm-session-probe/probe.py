#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://admllm.data-light.ru/v1"
DEFAULT_MODEL = "openai/gpt-5.5"
SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]+")


@dataclass
class HttpResult:
    ok: bool
    status: int | None
    data: dict[str, Any] | list[Any] | str | None
    error: str | None
    elapsed_ms: int


def build_first_response_payload(*, model: str, marker: str) -> dict[str, Any]:
    return {
        "model": model,
        "input": (
            "Session probe step 1. Remember this exact marker for the next request: "
            f"{marker}. Reply with only the word stored."
        ),
        "store": True,
        "max_output_tokens": 80,
    }


def build_followup_payload(*, model: str, marker: str, previous_response_id: str) -> dict[str, Any]:
    return {
        "model": model,
        "previous_response_id": previous_response_id,
        "input": (
            "Session probe step 2. What exact marker did I ask you to remember in the previous response? "
            f"Reply with only the marker. Expected marker shape: {marker}"
        ),
        "store": True,
        "max_output_tokens": 80,
    }


def build_background_payload(*, model: str, marker: str) -> dict[str, Any]:
    return {
        "model": model,
        "input": f"Background probe. Reply with this marker and nothing else: {marker}",
        "store": True,
        "background": True,
        "max_output_tokens": 80,
    }


def build_compact_payload(*, model: str, marker: str) -> dict[str, Any]:
    return {
        "model": model,
        "input": [
            {"role": "user", "content": f"Remember this compact marker: {marker}"},
            {"role": "assistant", "content": f"I will remember {marker}."},
        ],
    }


def extract_response_id(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    value = data.get("id") or data.get("response_id") or data.get("polling_id")
    return str(value) if value else None


def extract_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    output_text = data.get("output_text")
    if isinstance(output_text, str):
        return output_text

    parts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in {"authorization", "x-litellm-api-key", "api_key", "key"}:
                redacted[key] = "sk-..."
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return SECRET_PATTERN.sub("sk-...", value)
    return value


class AdmllmClient:
    def __init__(self, *, base_url: str, api_key: str, timeout_seconds: float, auth_header: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.auth_header = auth_header

    def post(self, path: str, payload: dict[str, Any]) -> HttpResult:
        return self._request("POST", path, payload=payload)

    def get(self, path: str) -> HttpResult:
        return self._request("GET", path, payload=None)

    def _request(self, method: str, path: str, *, payload: dict[str, Any] | None) -> HttpResult:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if self.auth_header in {"authorization", "both"}:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.auth_header in {"x-litellm-api-key", "both"}:
            headers["x-litellm-api-key"] = self.api_key

        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        started = time.monotonic()
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                return HttpResult(
                    ok=200 <= response.status < 300,
                    status=response.status,
                    data=_parse_json(raw),
                    error=None,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            return HttpResult(
                ok=False,
                status=exc.code,
                data=_parse_json(raw),
                error=str(exc),
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        except URLError as exc:
            return HttpResult(
                ok=False,
                status=None,
                data=None,
                error=str(exc.reason),
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )


def run_probe(*, client: AdmllmClient, model: str) -> dict[str, Any]:
    marker = f"admllm-probe-{uuid.uuid4().hex[:10]}"
    report: dict[str, Any] = {
        "created_at": datetime.now(tz=UTC).isoformat(),
        "base_url": client.base_url,
        "model": model,
        "marker": marker,
        "steps": {},
    }

    first = client.post("/responses", build_first_response_payload(model=model, marker=marker))
    first_id = extract_response_id(first.data)
    report["steps"]["create_response"] = _step_report(first, response_id=first_id, text=extract_text(first.data))

    if first_id:
        followup = client.post("/responses", build_followup_payload(model=model, marker=marker, previous_response_id=first_id))
        followup_text = extract_text(followup.data)
        report["steps"]["previous_response_followup"] = _step_report(
            followup,
            response_id=extract_response_id(followup.data),
            text=followup_text,
            remembered_marker=marker in followup_text,
        )

        get_response = client.get(f"/responses/{first_id}")
        report["steps"]["get_response"] = _step_report(get_response, response_id=extract_response_id(get_response.data))

        input_items = client.get(f"/responses/{first_id}/input_items")
        if _error_mentions_model_none(input_items):
            input_items_with_model = client.get(
                f"/responses/{first_id}/input_items?model={quote(model, safe='')}"
            )
            report["steps"]["input_items"] = {
                "initial_without_model": _step_report(input_items),
                "retry_with_model": _step_report(input_items_with_model),
                "ok": input_items_with_model.ok,
            }
        else:
            report["steps"]["input_items"] = _step_report(input_items)
    else:
        report["steps"]["previous_response_followup"] = {"ok": False, "skipped": "create_response returned no response id"}
        report["steps"]["get_response"] = {"ok": False, "skipped": "create_response returned no response id"}
        report["steps"]["input_items"] = {"ok": False, "skipped": "create_response returned no response id"}

    background = client.post("/responses", build_background_payload(model=model, marker=marker))
    background_id = extract_response_id(background.data)
    report["steps"]["background_response"] = _step_report(background, response_id=background_id, text=extract_text(background.data))
    if background_id:
        report["steps"]["background_poll"] = _poll_response(client=client, response_id=background_id, marker=marker)
    else:
        report["steps"]["background_poll"] = {"ok": False, "skipped": "background response returned no id"}

    compact = client.post("/responses/compact", build_compact_payload(model=model, marker=marker))
    report["steps"]["compact"] = _step_report(compact, response_id=extract_response_id(compact.data), text=extract_text(compact.data))

    report["summary"] = {
        "responses_create_supported": bool(report["steps"]["create_response"].get("ok")),
        "previous_response_id_supported": bool(report["steps"]["previous_response_followup"].get("ok")),
        "followup_remembered_marker": bool(report["steps"]["previous_response_followup"].get("remembered_marker")),
        "get_response_supported": bool(report["steps"]["get_response"].get("ok")),
        "input_items_supported": bool(report["steps"]["input_items"].get("ok")),
        "background_supported": bool(report["steps"]["background_response"].get("ok")),
        "background_poll_supported": bool(report["steps"]["background_poll"].get("ok")),
        "compact_supported": bool(report["steps"]["compact"].get("ok")),
    }
    return redact_secrets(report)


def _poll_response(*, client: AdmllmClient, response_id: str, marker: str) -> dict[str, Any]:
    polls = []
    for attempt in range(1, 6):
        time.sleep(1)
        result = client.get(f"/responses/{response_id}")
        text = extract_text(result.data)
        step = _step_report(result, response_id=extract_response_id(result.data), text=text, attempt=attempt)
        polls.append(step)
        if result.ok and (marker in text or _status(result.data) in {"completed", "failed", "cancelled"}):
            return {"ok": result.ok, "remembered_marker": marker in text, "polls": polls}
    return {"ok": False, "remembered_marker": False, "polls": polls}


def _step_report(result: HttpResult, **extra: Any) -> dict[str, Any]:
    usage = result.data.get("usage") if isinstance(result.data, dict) else None
    error_data = result.data if not result.ok else None
    return redact_secrets(
        {
            "ok": result.ok,
            "status": result.status,
            "elapsed_ms": result.elapsed_ms,
            "usage": usage,
            "error": result.error,
            "error_data": error_data,
            **{key: value for key, value in extra.items() if value is not None},
        }
    )


def _status(data: Any) -> str | None:
    if isinstance(data, dict):
        value = data.get("status")
        return str(value) if value else None
    return None


def _error_mentions_model_none(result: HttpResult) -> bool:
    return not result.ok and "model=None" in json.dumps(result.data, ensure_ascii=False)


def _parse_json(raw: str) -> dict[str, Any] | list[Any] | str | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw[:1000]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe admllm Responses API session behavior.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument("--auth-header", choices=["authorization", "x-litellm-api-key", "both"], default="authorization")
    parser.add_argument("--api-key-stdin", action="store_true", help="Read API key from stdin instead of ADMLLM_API_KEY.")
    parser.add_argument("--output", help="Optional path for JSON report.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    api_key = sys.stdin.readline().strip() if args.api_key_stdin else os.environ.get("ADMLLM_API_KEY", "")
    if not api_key:
        api_key = getpass.getpass("ADMLLM_API_KEY: ").strip()
    if not api_key:
        print("ADMLLM_API_KEY is required", file=sys.stderr)
        return 2

    client = AdmllmClient(
        base_url=args.base_url,
        api_key=api_key,
        timeout_seconds=args.timeout_seconds,
        auth_header=args.auth_header,
    )
    report = run_probe(client=client, model=args.model)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            file.write(rendered)
            file.write("\n")
    print(rendered)
    return 0 if report["summary"]["responses_create_supported"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

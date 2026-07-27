"""Runtime HTTP Provider adapter for direct single-call action generation."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

from typing import Any, Protocol, cast

from yagcode.secrets import CredentialBroker

from .base import ProviderContext, ProviderFailure, ProviderResult, Usage
from . import OfficialEndpoint


class Urlopen(Protocol):
    def __call__(self, request: urllib.request.Request, *, timeout: float) -> Any: ...

_ACTION_INSTRUCTIONS = """You are YagCode's single-call coding action generator.
Return exactly one JSON object and no markdown.
The JSON object must be one YagCode action:
list_directory, read_text, search_literal, apply_patch, git_inspect, run_command,
run_validation, or request_review.
Use root_id "project" for workspace files. Prefer read_text/search_literal before
apply_patch. End with request_review when the diff is ready for the user.
Do not include credentials or hidden chain-of-thought in the JSON."""


class HttpJsonActionProvider:
    """Call a configured Provider endpoint and decode exactly one JSON action."""

    def __init__(
        self,
        *,
        endpoints: dict[str, OfficialEndpoint],
        credentials: CredentialBroker,
        profile_id: str,
        urlopen: Urlopen | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 5,
    ) -> None:
        self._endpoints = endpoints
        self._credentials = credentials
        self._profile_id = profile_id
        self._urlopen: Urlopen = cast(Urlopen, urllib.request.urlopen) if urlopen is None else urlopen
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    def complete_once(self, context: ProviderContext) -> ProviderResult | ProviderFailure:
        endpoint = self._endpoints.get(context.provider)
        if endpoint is None:
            return _failure(context, "PROVIDER_ENDPOINT_UNKNOWN")
        try:
            ref = self._credentials.reference(self._profile_id, context.provider)
            authorization = self._credentials.authorization_for(self._credentials.acquire(ref))
        except (LookupError, RuntimeError):
            return _failure(context, "PROVIDER_CREDENTIAL_MISSING")

        body = _request_body(endpoint.url, context)
        headers = {
            "Accept": "application/json",
            "Authorization": authorization,
            "Content-Type": "application/json",
        }
        for attempt in range(self._max_retries + 1):
            request = urllib.request.Request(
                endpoint.url,
                data=body,
                headers=headers,
                method=endpoint.method,
            )
            try:
                with self._urlopen(request, timeout=self._timeout_seconds) as response:
                    status_code = int(response.getcode())
                    raw = response.read()
            except urllib.error.HTTPError as error:
                if _retryable_status(error.code) and attempt < self._max_retries:
                    continue
                return _failure(context, _http_error_code(error.code))
            except (TimeoutError, urllib.error.URLError, socket.timeout, OSError) as error:
                if attempt < self._max_retries:
                    continue
                return _failure(context, f"PROVIDER_NETWORK_ERROR:{type(error).__name__}")

            if _retryable_status(status_code) and attempt < self._max_retries:
                continue
            if not 200 <= status_code < 300:
                return _failure(context, _http_error_code(status_code))
            return _decode_response(context, endpoint.url, raw)
        return _failure(context, "PROVIDER_RETRY_EXHAUSTED")


def _request_body(endpoint_url: str, context: ProviderContext) -> bytes:
    if endpoint_url.endswith("/responses"):
        payload: dict[str, object] = {
            "model": context.model,
            "instructions": _ACTION_INSTRUCTIONS,
            "input": context.prompt,
            "store": False,
            "text": {"format": {"type": "json_object"}},
            "max_output_tokens": 1500,
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")
    payload = {
        "model": context.model,
        "messages": [
            {"role": "system", "content": _ACTION_INSTRUCTIONS},
            {"role": "user", "content": context.prompt},
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
        "temperature": 0,
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _decode_response(
    context: ProviderContext,
    endpoint_url: str,
    raw: bytes,
) -> ProviderResult | ProviderFailure:
    try:
        decoded = json.loads(raw.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("PROVIDER_RESPONSE_SHAPE_INVALID")
        candidate = _extract_openai_response(decoded) if endpoint_url.endswith("/responses") else _extract_chat(decoded)
    except (KeyError, TypeError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        return _failure(context, _safe_error(error))
    return ProviderResult.from_candidate(
        context.provider,
        context.model,
        context.generation,
        candidate,
        usage=_usage(decoded),
    )


def _extract_chat(decoded: dict[str, object]) -> object:
    choices = decoded["choices"]
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("PROVIDER_CANDIDATE_COUNT_INVALID")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError("PROVIDER_RESPONSE_SHAPE_INVALID")
    message = choice["message"]
    if not isinstance(message, dict):
        raise ValueError("PROVIDER_RESPONSE_SHAPE_INVALID")
    content = message["content"]
    return _json_candidate(content)


def _extract_openai_response(decoded: dict[str, object]) -> object:
    output = decoded["output"]
    if not isinstance(output, list):
        raise ValueError("PROVIDER_RESPONSE_SHAPE_INVALID")
    candidates: list[object] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            raise ValueError("PROVIDER_RESPONSE_SHAPE_INVALID")
        for content_item in content:
            if not isinstance(content_item, dict):
                raise ValueError("PROVIDER_RESPONSE_SHAPE_INVALID")
            if "json" in content_item:
                candidates.append(content_item["json"])
            elif "text" in content_item:
                candidates.append(_json_candidate(content_item["text"]))
    if len(candidates) != 1:
        raise ValueError("PROVIDER_CANDIDATE_COUNT_INVALID")
    return candidates[0]


def _json_candidate(value: object) -> object:
    if isinstance(value, str):
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise ValueError("PROVIDER_CANDIDATE_INVALID")
        return decoded
    return value


def _usage(decoded: dict[str, object]) -> Usage | None:
    usage = decoded.get("usage")
    if not isinstance(usage, dict):
        return None
    return Usage(
        input_tokens=_optional_int(usage.get("input_tokens", usage.get("prompt_tokens"))),
        output_tokens=_optional_int(usage.get("output_tokens", usage.get("completion_tokens"))),
        total_tokens=_optional_int(usage.get("total_tokens")),
    )


def _optional_int(value: object) -> int | None:
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _retryable_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code < 600


def _http_error_code(status_code: int) -> str:
    return f"PROVIDER_HTTP_{status_code}"


def _safe_error(error: BaseException) -> str:
    text = str(error)
    if not text or "\x00" in text or len(text) > 128:
        return "PROVIDER_RESPONSE_INVALID"
    return text


def _failure(context: ProviderContext, reason: str) -> ProviderFailure:
    return ProviderFailure(context.provider, context.model, context.generation, reason)


__all__ = ["HttpJsonActionProvider"]

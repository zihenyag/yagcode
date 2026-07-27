"""Runtime Provider credential validation for the desktop sidecar."""

from __future__ import annotations

import socket
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from urllib.parse import urlparse, urlunparse

from yagcode.providers import OfficialEndpoint, load_official_endpoints


VerificationState = Literal["verified", "error"]


class Clock(Protocol):
    def __call__(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class ProviderVerificationResult:
    provider: str
    status: VerificationState
    checked_at: datetime
    detail: str
    models: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "verified"


class ProviderCredentialVerifier(Protocol):
    def verify(self, provider: str, api_key: str) -> ProviderVerificationResult: ...


class HttpProviderCredentialVerifier:
    """Validate credentials with a lightweight authenticated Provider request."""

    def __init__(
        self,
        *,
        endpoints: dict[str, OfficialEndpoint] | None = None,
        timeout_seconds: float = 8.0,
        clock: Clock | None = None,
    ) -> None:
        self._endpoints = endpoints if endpoints is not None else load_official_endpoints()
        self._timeout_seconds = timeout_seconds
        self._clock = clock if clock is not None else _utc_now

    def verify(self, provider: str, api_key: str) -> ProviderVerificationResult:
        endpoint = self._endpoints.get(provider)
        if endpoint is None:
            return self._result(provider, "error", "PROVIDER_ENDPOINT_UNKNOWN")
        models_url = _models_url(endpoint.url)
        if models_url is None:
            return self._result(provider, "error", "PROVIDER_ENDPOINT_INVALID")
        request = urllib.request.Request(
            models_url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                status_code = response.getcode()
                raw = response.read(262_144)
        except urllib.error.HTTPError as error:
            return self._result(provider, "error", _http_error_detail(error.code))
        except (TimeoutError, urllib.error.URLError, socket.timeout, OSError) as error:
            return self._result(provider, "error", f"PROVIDER_VALIDATION_NETWORK_ERROR:{type(error).__name__}")
        if 200 <= status_code < 300:
            return self._result(provider, "verified", "GET /models verified", models=_extract_model_ids(raw))
        return self._result(provider, "error", _http_error_detail(status_code))

    def _result(
        self,
        provider: str,
        status: VerificationState,
        detail: str,
        *,
        models: tuple[str, ...] = (),
    ) -> ProviderVerificationResult:
        return ProviderVerificationResult(provider, status, self._clock(), detail, models=models)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _http_error_detail(status_code: int) -> str:
    if status_code in {401, 403}:
        return "PROVIDER_AUTH_REJECTED"
    if status_code == 429:
        return "PROVIDER_RATE_LIMITED"
    if 500 <= status_code < 600:
        return "PROVIDER_TEMPORARY_FAILURE"
    return f"PROVIDER_HTTP_{status_code}"


def _models_url(endpoint_url: str) -> str | None:
    parsed = urlparse(endpoint_url)
    if parsed.scheme != "https" or parsed.hostname is None:
        return None
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    elif path.endswith("/responses"):
        path = path[: -len("/responses")]
    else:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, f"{path}/models", "", "", ""))


def _extract_model_ids(raw: bytes) -> tuple[str, ...]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return ()
    if not isinstance(decoded, dict):
        return ()
    data = decoded.get("data")
    if not isinstance(data, list):
        return ()
    ids: list[str] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id or "\x00" in model_id or model_id in seen:
            continue
        ids.append(model_id)
        seen.add(model_id)
    return tuple(ids)


__all__ = [
    "HttpProviderCredentialVerifier",
    "ProviderCredentialVerifier",
    "ProviderVerificationResult",
]

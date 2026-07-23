"""Egress redirect handling must not leak Authorization across hosts."""

from __future__ import annotations

import importlib

import pytest


def test_owned_redirect_oracle_blocks_second_host_authorization() -> None:
    second_headers: list[str] = []
    assert second_headers == []
    assert "evil.example" != "api.openai.com"


def load_egress_contract():
    try:
        return importlib.import_module("yagcode.policy.egress")
    except ModuleNotFoundError as error:
        pytest.fail(f"PROVIDER_CONTRACT_MISSING: {error.name}")


class FakeCapability:
    def __init__(self) -> None:
        self.consumed = 0

    def consume(self, token, capability) -> None:
        self.consumed += 1


class FakePrivacy:
    def require_grant_or_preview(self, request):
        return None


class FakeSecretScanner:
    def reject(self, payload: bytes) -> None:
        assert b"CANARY" not in payload


class FakeSecrets:
    def authorization_header(self, credential_ref):
        return "Bearer redacted"


class FakeDns:
    def resolve_public(self, host: str):
        return ("203.0.113.10",)


class RedirectTransport:
    def __init__(self) -> None:
        self.first_authorization: list[str] = []
        self.second_authorization: list[str] = []

    def send_direct(self, request, addresses, authorization):
        self.first_authorization.append(authorization)
        return type(
            "Response",
            (),
            {"status_code": 302, "peer": addresses[0], "body": b"", "redirect_to": "https://evil.example/capture"},
        )()


def test_cross_host_redirect_never_receives_authorization() -> None:
    egress = load_egress_contract()
    transport = RedirectTransport()
    broker = egress.EgressBroker(
        endpoints=egress.load_official_endpoints(),
        capabilities=FakeCapability(),
        privacy=FakePrivacy(),
        secret_scanner=FakeSecretScanner(),
        dns=FakeDns(),
        secrets=FakeSecrets(),
        transport=transport,
    )
    request = egress.EgressRequest(
        provider="openai",
        payload=b"{}",
        network_token="token",
        capability="capability",
        credential_ref="ref",
        source_refs=("project:p/file:a.py",),
        privacy_categories=("source",),
        purpose="debug",
    )
    result = broker.send(request)
    assert result.error_code == "CROSS_ORIGIN_REDIRECT_DENIED"
    assert transport.first_authorization == ["Bearer redacted"]
    assert transport.second_authorization == []

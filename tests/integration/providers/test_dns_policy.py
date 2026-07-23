"""DNS and peer checks happen before trusted Provider egress succeeds."""

from __future__ import annotations

import importlib

import pytest


def test_owned_dns_oracle_rejects_special_addresses() -> None:
    assert "127.0.0.1".startswith("127.")
    assert not "203.0.113.10".startswith("127.")


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
        return None


class FakeSecrets:
    def __init__(self) -> None:
        self.calls = 0

    def authorization_header(self, credential_ref):
        self.calls += 1
        return "Bearer redacted"


class FakeDns:
    def __init__(self, addresses: tuple[str, ...]) -> None:
        self.addresses = addresses

    def resolve_public(self, host: str):
        return self.addresses


class PeerTransport:
    def __init__(self, peer: str) -> None:
        self.peer = peer
        self.calls = 0

    def send_direct(self, request, addresses, authorization):
        self.calls += 1
        return type(
            "Response",
            (),
            {"status_code": 200, "peer": self.peer, "body": b"{}", "redirect_to": None},
        )()


def _request(egress):
    return egress.EgressRequest(
        provider="openai",
        payload=b"{}",
        network_token="token",
        capability="capability",
        credential_ref="ref",
        source_refs=("project:p/file:a.py",),
        privacy_categories=("source",),
        purpose="debug",
    )


def test_special_address_is_rejected_before_auth_and_transport() -> None:
    egress = load_egress_contract()
    secrets = FakeSecrets()
    transport = PeerTransport("127.0.0.1")
    broker = egress.EgressBroker(
        endpoints=egress.load_official_endpoints(),
        capabilities=FakeCapability(),
        privacy=FakePrivacy(),
        secret_scanner=FakeSecretScanner(),
        dns=FakeDns(("127.0.0.1",)),
        secrets=secrets,
        transport=transport,
    )
    result = broker.send(_request(egress))
    assert result.error_code == "DNS_SPECIAL_ADDRESS_DENIED"
    assert secrets.calls == 0
    assert transport.calls == 0


def test_peer_mismatch_fails_after_single_direct_send() -> None:
    egress = load_egress_contract()
    transport = PeerTransport("203.0.113.99")
    broker = egress.EgressBroker(
        endpoints=egress.load_official_endpoints(),
        capabilities=FakeCapability(),
        privacy=FakePrivacy(),
        secret_scanner=FakeSecretScanner(),
        dns=FakeDns(("203.0.113.10",)),
        secrets=FakeSecrets(),
        transport=transport,
    )
    result = broker.send(_request(egress))
    assert result.error_code == "TLS_PEER_ADDRESS_MISMATCH"
    assert transport.calls == 1

"""Deterministic Provider egress gate with credential and redirect isolation."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from yagcode.providers import OfficialEndpoint, load_official_endpoints


@dataclass(frozen=True, slots=True)
class EgressRequest:
    provider: str
    payload: bytes
    network_token: object
    capability: object
    credential_ref: object
    source_refs: tuple[str, ...]
    privacy_categories: tuple[str, ...]
    purpose: str


@dataclass(frozen=True, slots=True)
class EgressReceipt:
    provider: str
    url: str
    status_code: int
    peer: str
    body: bytes
    error_code: None = None


@dataclass(frozen=True, slots=True)
class EgressFailure:
    error_code: str


class CapabilityGate(Protocol):
    def consume(self, token: object, capability: object) -> object: ...


class PrivacyGate(Protocol):
    def require_grant_or_preview(self, request: EgressRequest) -> object: ...


class SecretScanner(Protocol):
    def reject(self, payload: bytes) -> object: ...


class DnsResolver(Protocol):
    def resolve_public(self, host: str) -> Iterable[str]: ...


class SecretAuthorizer(Protocol):
    def authorization_header(self, credential_ref: object) -> str: ...


class DirectEgressTransport(Protocol):
    def send_direct(
        self,
        request: EgressRequest,
        addresses: tuple[str, ...],
        authorization: str,
    ) -> object: ...


class EgressBroker:
    def __init__(
        self,
        *,
        endpoints: Mapping[str, OfficialEndpoint],
        capabilities: CapabilityGate,
        privacy: PrivacyGate,
        secret_scanner: SecretScanner,
        dns: DnsResolver,
        secrets: SecretAuthorizer,
        transport: DirectEgressTransport,
    ) -> None:
        self._endpoints = dict(endpoints)
        self._capabilities = capabilities
        self._privacy = privacy
        self._secret_scanner = secret_scanner
        self._dns = dns
        self._secrets = secrets
        self._transport = transport

    def send(self, request: EgressRequest) -> EgressReceipt | EgressFailure:
        endpoint = self._endpoints.get(request.provider)
        if endpoint is None:
            return EgressFailure("PROVIDER_ENDPOINT_UNKNOWN")
        origin = _official_origin(endpoint)
        if origin is None:
            return EgressFailure("PROVIDER_ENDPOINT_INVALID")

        capability_error = _decision_error(self._capabilities.consume(request.network_token, request.capability))
        if capability_error is not None:
            return EgressFailure(capability_error)

        privacy_error = _decision_error(self._privacy.require_grant_or_preview(request))
        if privacy_error is not None:
            return EgressFailure(privacy_error)

        scan_error = _scanner_error(self._secret_scanner.reject, request.payload)
        if scan_error is not None:
            return EgressFailure(scan_error)

        addresses = tuple(self._dns.resolve_public(origin.host))
        if not addresses:
            return EgressFailure("DNS_NO_PUBLIC_ADDRESS")
        if any(_is_special_address(address) for address in addresses):
            return EgressFailure("DNS_SPECIAL_ADDRESS_DENIED")

        authorization = self._secrets.authorization_header(request.credential_ref)
        response = self._transport.send_direct(request, addresses, authorization)

        redirect_to = getattr(response, "redirect_to", None)
        if type(redirect_to) is str and redirect_to:
            redirect_host = urlparse(redirect_to).hostname
            if redirect_host != origin.host:
                return EgressFailure("CROSS_ORIGIN_REDIRECT_DENIED")
            return EgressFailure("REDIRECT_DENIED")

        peer = getattr(response, "peer", None)
        if type(peer) is not str or peer not in addresses:
            return EgressFailure("TLS_PEER_ADDRESS_MISMATCH")

        status_code = getattr(response, "status_code", None)
        body = getattr(response, "body", None)
        if type(status_code) is not int or type(body) is not bytes:
            return EgressFailure("TRANSPORT_RESPONSE_INVALID")
        return EgressReceipt(request.provider, endpoint.url, status_code, peer, body)


@dataclass(frozen=True, slots=True)
class _Origin:
    host: str


def _official_origin(endpoint: OfficialEndpoint) -> _Origin | None:
    parsed = urlparse(endpoint.url)
    if endpoint.method != "POST" or parsed.scheme != "https" or parsed.hostname is None:
        return None
    return _Origin(parsed.hostname)


def _decision_error(decision: object) -> str | None:
    if decision is None:
        return None
    allowed = getattr(decision, "allowed", None)
    if allowed is False:
        reason_code = getattr(decision, "reason_code", None)
        if type(reason_code) is str and reason_code:
            return reason_code
        return "EGRESS_POLICY_DENIED"
    return None


def _scanner_error(reject: object, payload: bytes) -> str | None:
    try:
        reject(payload)  # type: ignore[operator]
    except Exception:
        return "SECRET_SCAN_DENIED"
    return None


def _is_special_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    rfc1918_networks = (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("fc00::/7"),
    )
    return (
        parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_unspecified
        or any(parsed in network for network in rfc1918_networks)
    )


__all__ = [
    "DirectEgressTransport",
    "DnsResolver",
    "EgressBroker",
    "EgressFailure",
    "EgressReceipt",
    "EgressRequest",
    "load_official_endpoints",
]

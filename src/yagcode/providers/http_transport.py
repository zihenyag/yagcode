"""Transport value objects for direct single-call Provider egress."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    peer: str
    body: bytes
    redirect_to: str | None = None


class DirectTransport(Protocol):
    def send_direct(self, request: object, addresses: tuple[str, ...], authorization: str) -> object: ...


__all__ = ["DirectTransport", "HttpRequest", "HttpResponse"]

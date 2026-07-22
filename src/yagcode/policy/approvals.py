"""Main-only one-shot approval challenges backed by atomic repository consumption."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Callable

from .intents import IntentBinding, RendererIntentRequest


_RENDERER_REQUEST_KINDS = frozenset(
    {
        "plan",
        "permission",
        "approve_permission",
        "privacy",
        "full_access",
        "accept",
        "commit",
        "branch",
        "push",
        "git_install",
        "git_init",
        "credential_update",
        "credential_clear",
        "profile_delete",
    }
)


@dataclass(frozen=True, slots=True)
class IntentDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class IntentRecord:
    token_digest: str
    binding_digest: str
    expires_at: datetime
    consumed: bool = False
    expired: bool = False


class InMemoryIntentRepository:
    """Deterministic repository fake; a durable adapter must provide the same transaction."""

    def __init__(self) -> None:
        self._records: list[IntentRecord] = []
        self._renderer_requests: dict[str, IntentBinding] = {}
        self._lock = threading.RLock()
        self.authorized_system_actions = 0

    def add(self, record: IntentRecord) -> bool:
        with self._lock:
            if any(
                hmac.compare_digest(existing.token_digest, record.token_digest)
                for existing in self._records
            ):
                return False
            self._records.append(record)
            return True

    def records(self) -> tuple[IntentRecord, ...]:
        with self._lock:
            return tuple(self._records)

    def add_renderer_request(self, request_id: str, binding: IntentBinding) -> None:
        with self._lock:
            if request_id in self._renderer_requests:
                raise ValueError("APPROVAL_REQUEST_ID_COLLISION")
            self._renderer_requests[request_id] = binding

    def issue_renderer_request(
        self,
        request_id: str,
        issue: Callable[[IntentBinding], str],
    ) -> str | None:
        with self._lock:
            binding = self._renderer_requests.get(request_id)
            if binding is None:
                return None
            token = issue(binding)
            del self._renderer_requests[request_id]
            return token

    def consume_and_create(
        self,
        *,
        token_digest: str,
        binding_digest_for_expiry: Callable[[datetime], str],
        now: datetime,
        create_system_action: Callable[[], None],
    ) -> IntentDecision:
        with self._lock:
            index = next(
                (
                    candidate
                    for candidate, record in enumerate(self._records)
                    if hmac.compare_digest(record.token_digest, token_digest)
                ),
                None,
            )
            if index is None:
                return IntentDecision(False, "APPROVAL_TOKEN_INVALID")
            record = self._records[index]
            if record.consumed:
                return IntentDecision(False, "APPROVAL_TOKEN_CONSUMED")
            if record.expired or now >= record.expires_at:
                self._records[index] = replace(record, expired=True)
                return IntentDecision(False, "APPROVAL_TOKEN_EXPIRED")
            expected_binding = binding_digest_for_expiry(record.expires_at)
            if not hmac.compare_digest(record.binding_digest, expected_binding):
                return IntentDecision(False, "APPROVAL_BINDING_MISMATCH")
            create_system_action()
            self._records[index] = replace(record, consumed=True)
            self.authorized_system_actions += 1
            return IntentDecision(True, "ALLOWED")


class ApprovalService:
    def __init__(
        self,
        repository: InMemoryIntentRepository,
        *,
        key: bytes,
        clock: Callable[[], datetime],
        ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        if type(key) is not bytes or len(key) < 32:
            raise ValueError("APPROVAL_HMAC_KEY_INVALID")
        if ttl <= timedelta(0):
            raise ValueError("APPROVAL_TTL_INVALID")
        self.repository = repository
        self._key = key
        self._clock = clock
        self._ttl = ttl

    def request_from_renderer(self, binding: IntentBinding, kind: str) -> RendererIntentRequest:
        if type(binding) is not IntentBinding or not binding.is_valid():
            raise ValueError("APPROVAL_BINDING_INVALID")
        if binding.consistency_error() is not None:
            raise ValueError(binding.consistency_error())
        if type(kind) is not str or kind not in _RENDERER_REQUEST_KINDS:
            raise ValueError("APPROVAL_KIND_INVALID")
        request_id = secrets.token_urlsafe(24)
        request = RendererIntentRequest(
            request_id=request_id,
            kind=kind,
            binding_digest=self._binding_digest(binding, None),
        )
        self.repository.add_renderer_request(request_id, binding)
        return request

    def issue_requested_for_main(self, request_id: str) -> str:
        if type(request_id) is not str or not request_id or "\x00" in request_id:
            raise ValueError("APPROVAL_REQUEST_INVALID")
        token = self.repository.issue_renderer_request(request_id, self.issue_for_main)
        if token is None:
            raise ValueError("APPROVAL_REQUEST_INVALID")
        return token

    def issue_for_renderer(self, binding: IntentBinding) -> str:
        del binding
        raise PermissionError("MAIN_CHANNEL_REQUIRED")

    def consume_for_renderer(self, token: str, binding: IntentBinding) -> IntentDecision:
        del token, binding
        raise PermissionError("MAIN_CHANNEL_REQUIRED")

    def issue_for_main(self, binding: IntentBinding) -> str:
        if type(binding) is not IntentBinding or not binding.is_valid():
            raise ValueError("APPROVAL_BINDING_INVALID")
        if binding.consistency_error() is not None:
            raise ValueError(binding.consistency_error())
        now = self._now()
        expires_at = now + self._ttl
        for _ in range(8):
            token = secrets.token_urlsafe(32)
            if self.repository.add(
                IntentRecord(
                    token_digest=self._token_digest(token),
                    binding_digest=self._binding_digest(binding, expires_at),
                    expires_at=expires_at,
                )
            ):
                return token
        raise RuntimeError("APPROVAL_TOKEN_GENERATION_COLLISION")

    def consume_for_main(self, token: str, binding: IntentBinding) -> IntentDecision:
        return self.consume_and_create_system_action(token, binding, lambda: None)

    def consume_and_create_system_action(
        self,
        token: str,
        binding: IntentBinding,
        create_system_action: Callable[[], None],
    ) -> IntentDecision:
        if type(token) is not str or not token or "\x00" in token:
            return IntentDecision(False, "APPROVAL_TOKEN_INVALID")
        if type(binding) is not IntentBinding or not binding.is_valid():
            return IntentDecision(False, "APPROVAL_BINDING_MISMATCH")
        return self.repository.consume_and_create(
            token_digest=self._token_digest(token),
            binding_digest_for_expiry=lambda expiry: self._binding_digest(binding, expiry),
            now=self._now(),
            create_system_action=create_system_action,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("APPROVAL_CLOCK_INVALID")
        return value.astimezone(UTC)

    def _token_digest(self, token: str) -> str:
        return hmac.new(self._key, token.encode("utf-8"), hashlib.sha256).hexdigest()

    def _binding_digest(self, binding: IntentBinding, expires_at: datetime | None) -> str:
        expiry = b"renderer-request" if expires_at is None else expires_at.astimezone(UTC).isoformat(
            timespec="microseconds"
        ).encode("ascii")
        framed = len(binding.canonical_bytes()).to_bytes(8, "big") + binding.canonical_bytes() + expiry
        return hmac.new(self._key, framed, hashlib.sha256).hexdigest()


__all__ = [
    "ApprovalService",
    "InMemoryIntentRepository",
    "IntentDecision",
    "IntentRecord",
]

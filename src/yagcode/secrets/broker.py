"""Opaque Provider credential lifecycle; plaintext stays inside the keyring path."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .keyring_store import KeyringStore


Clock = Callable[[], datetime]
CredentialValidator = Callable[["CredentialRef"], bool]


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _validate_text(name: str, value: object) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise ValueError(f"{name}_INVALID")
    return value


@dataclass(frozen=True, slots=True)
class CredentialRef:
    profile_id: str
    provider: str
    keyring_service: str
    keyring_account: str
    updated_at: datetime
    generation: int

    def __post_init__(self) -> None:
        _validate_text("PROFILE_ID", self.profile_id)
        _validate_text("PROVIDER", self.provider)
        _validate_text("KEYRING_SERVICE", self.keyring_service)
        _validate_text("KEYRING_ACCOUNT", self.keyring_account)
        if self.updated_at.tzinfo is None:
            raise ValueError("UPDATED_AT_TZ_REQUIRED")
        if self.generation < 0:
            raise ValueError("CREDENTIAL_GENERATION_INVALID")


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    provider: str
    state: str
    updated_at: datetime | None
    connection_state: str


@dataclass(frozen=True, slots=True)
class CredentialHandle:
    ref: CredentialRef


class CredentialBroker:
    def __init__(
        self,
        keyring: KeyringStore,
        *,
        service_prefix: str = "yagcode",
        clock: Clock = _default_clock,
    ) -> None:
        self._keyring = keyring
        self._service_prefix = _validate_text("KEYRING_SERVICE_PREFIX", service_prefix)
        self._clock = clock
        self._refs: dict[tuple[str, str], CredentialRef] = {}
        self._invalidated: set[tuple[str, str, int]] = set()

    def _service(self, profile_id: str, provider: str) -> str:
        return f"{self._service_prefix}:{profile_id}:{provider}"

    def _account(self, provider: str, *, temporary: bool = False) -> str:
        prefix = "tmp" if temporary else "active"
        return f"{provider}:{prefix}:{secrets.token_urlsafe(18)}"

    def enroll(self, profile_id: str, provider: str, secret_value: str) -> CredentialRef:
        _validate_text("PROFILE_ID", profile_id)
        _validate_text("PROVIDER", provider)
        _validate_text("SECRET", secret_value)
        key = (profile_id, provider)
        service = self._service(profile_id, provider)
        account = self._account(provider)
        self._keyring.set_password(service, account, secret_value)
        old = self._refs.get(key)
        generation = 0 if old is None else old.generation + 1
        ref = CredentialRef(profile_id, provider, service, account, self._clock(), generation)
        self._refs[key] = ref
        if old is not None:
            self._invalidated.add((old.profile_id, old.provider, old.generation))
            self._keyring.delete_password(old.keyring_service, old.keyring_account)
        return ref

    def reference(self, profile_id: str, provider: str) -> CredentialRef:
        try:
            return self._refs[(profile_id, provider)]
        except KeyError as error:
            raise LookupError("CREDENTIAL_REF_MISSING") from error

    def status(self, profile_id: str, provider: str) -> CredentialStatus:
        ref = self._refs.get((profile_id, provider))
        if ref is None:
            return CredentialStatus(provider, "MISSING", None, "UNKNOWN")
        return CredentialStatus(provider, "ENROLLED", ref.updated_at, "UNKNOWN")

    def update(
        self,
        profile_id: str,
        provider: str,
        secret_value: str,
        validator: CredentialValidator,
    ) -> CredentialRef:
        old = self.reference(profile_id, provider)
        _validate_text("SECRET", secret_value)
        temp_account = self._account(provider, temporary=True)
        self._keyring.set_password(old.keyring_service, temp_account, secret_value)
        candidate = CredentialRef(
            profile_id,
            provider,
            old.keyring_service,
            temp_account,
            self._clock(),
            old.generation + 1,
        )
        if not validator(candidate):
            self._keyring.delete_password(old.keyring_service, temp_account)
            raise ValueError("CREDENTIAL_VALIDATION_FAILED")
        self._refs[(profile_id, provider)] = candidate
        self._invalidated.add((old.profile_id, old.provider, old.generation))
        self._keyring.delete_password(old.keyring_service, old.keyring_account)
        return candidate

    def clear(self, profile_id: str, provider: str) -> CredentialStatus:
        ref = self.reference(profile_id, provider)
        self._invalidated.add((ref.profile_id, ref.provider, ref.generation))
        self._refs.pop((profile_id, provider), None)
        self._keyring.delete_password(ref.keyring_service, ref.keyring_account)
        return CredentialStatus(provider, "CLEARED", self._clock(), "UNKNOWN")

    def acquire(self, ref: CredentialRef) -> CredentialHandle:
        current = self.reference(ref.profile_id, ref.provider)
        if current != ref:
            raise RuntimeError("CREDENTIAL_HANDLE_INVALID")
        return CredentialHandle(ref)

    def authorization_for(self, handle: CredentialHandle) -> str:
        ref = handle.ref
        if (ref.profile_id, ref.provider, ref.generation) in self._invalidated:
            raise RuntimeError("CREDENTIAL_HANDLE_INVALID")
        current = self.reference(ref.profile_id, ref.provider)
        if current != ref:
            raise RuntimeError("CREDENTIAL_HANDLE_INVALID")
        secret_value = self._keyring.get_password(ref.keyring_service, ref.keyring_account)
        if secret_value is None:
            raise RuntimeError("CREDENTIAL_HANDLE_INVALID")
        return f"Bearer {secret_value}"


__all__ = ["CredentialBroker", "CredentialHandle", "CredentialRef", "CredentialStatus"]

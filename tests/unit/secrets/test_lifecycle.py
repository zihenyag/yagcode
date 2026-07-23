"""Credential lifecycle contracts; production is loaded only inside test cases."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest


class _Keyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.deleted: list[tuple[str, str]] = []

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def delete_password(self, service: str, account: str) -> None:
        self.deleted.append((service, account))
        self.values.pop((service, account), None)


def test_owned_fake_keyring_lifecycle_oracle() -> None:
    keyring = _Keyring()
    keyring.set_password("svc", "first", "secret")
    assert keyring.get_password("svc", "first") == "secret"
    keyring.delete_password("svc", "first")
    assert keyring.get_password("svc", "first") is None


def _broker() -> tuple[object, _Keyring]:
    production = importlib.import_module("yagcode.secrets.broker")
    keyring = _Keyring()
    return production.CredentialBroker(keyring, clock=lambda: datetime(2026, 1, 1, tzinfo=UTC)), keyring


def test_status_never_returns_or_reads_secret_plaintext() -> None:
    broker, keyring = _broker()
    ref = broker.enroll("profile", "openai", "CANARY-secret-value")
    before = dict(keyring.values)
    status = broker.status("profile", "openai")
    assert status.provider == "openai"
    assert status.state == "ENROLLED"
    assert "CANARY" not in repr(status)
    assert keyring.values == before
    assert ref.keyring_account not in repr(status)


def test_update_validates_temp_then_switches_and_deletes_old() -> None:
    broker, keyring = _broker()
    old = broker.enroll("profile", "openai", "old")
    updated = broker.update("profile", "openai", "new", lambda ref: keyring.get_password(ref.keyring_service, ref.keyring_account) == "new")
    assert updated.keyring_account != old.keyring_account
    assert (old.keyring_service, old.keyring_account) in keyring.deleted
    assert keyring.get_password(updated.keyring_service, updated.keyring_account) == "new"
    assert broker.status("profile", "openai").state == "ENROLLED"


def test_failed_update_leaves_existing_reference_intact() -> None:
    broker, keyring = _broker()
    old = broker.enroll("profile", "openai", "old")
    with pytest.raises(ValueError, match="CREDENTIAL_VALIDATION_FAILED"):
        broker.update("profile", "openai", "bad", lambda _ref: False)
    assert broker.reference("profile", "openai") == old
    assert keyring.get_password(old.keyring_service, old.keyring_account) == "old"


def test_clear_invalidates_handles_before_deleting_without_secret() -> None:
    broker, keyring = _broker()
    ref = broker.enroll("profile", "openai", "CANARY-secret-value")
    handle = broker.acquire(ref)
    status = broker.clear("profile", "openai")
    assert status.state == "CLEARED"
    assert "CANARY" not in repr(status)
    assert (ref.keyring_service, ref.keyring_account) in keyring.deleted
    with pytest.raises(RuntimeError, match="CREDENTIAL_HANDLE_INVALID"):
        broker.authorization_for(handle)

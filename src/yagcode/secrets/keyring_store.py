"""Narrow keyring protocol used by the credential broker."""

from __future__ import annotations

from typing import Protocol


class KeyringStore(Protocol):
    def set_password(self, service: str, account: str, value: str) -> None: ...

    def get_password(self, service: str, account: str) -> str | None: ...

    def delete_password(self, service: str, account: str) -> None: ...


__all__ = ["KeyringStore"]

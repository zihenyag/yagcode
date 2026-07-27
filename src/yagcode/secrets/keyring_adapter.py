"""Production OS keyring adapter for Provider credentials."""

from __future__ import annotations

import keyring


class KeyringModuleStore:
    def set_password(self, service: str, account: str, value: str) -> None:
        keyring.set_password(service, account, value)

    def get_password(self, service: str, account: str) -> str | None:
        return keyring.get_password(service, account)

    def delete_password(self, service: str, account: str) -> None:
        try:
            keyring.delete_password(service, account)
        except keyring.errors.PasswordDeleteError:
            return


__all__ = ["KeyringModuleStore"]

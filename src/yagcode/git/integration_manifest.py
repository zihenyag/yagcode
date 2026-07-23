"""Immutable acceptance manifests for applying verified agent changes."""

from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Literal

from yagcode.domain.errors import DomainError


IntegrationOperation = Literal["create", "replace", "delete", "rename", "chmod"]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class IntegrationManifestError(DomainError):
    """The accept manifest is malformed or unsafe to execute."""


def _valid_hash(value: str | None) -> bool:
    return value is None or (type(value) is str and _SHA256.fullmatch(value) is not None)


@dataclass(frozen=True, slots=True)
class IntegrationEntryPlan:
    sequence: int
    operation: IntegrationOperation
    path: str
    content: bytes | None = None
    preimage_hash: str | None = None
    planned_postimage_hash: str | None = None
    mode: int | None = None
    destination_path: str | None = None
    backup_ref: str | None = None

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise IntegrationManifestError("INTEGRATION_SEQUENCE_INVALID")
        if self.operation not in {"create", "replace", "delete", "rename", "chmod"}:
            raise IntegrationManifestError("INTEGRATION_OPERATION_INVALID")
        if type(self.path) is not str or not self.path:
            raise IntegrationManifestError("INTEGRATION_PATH_INVALID")
        if self.content is not None and type(self.content) is not bytes:
            raise IntegrationManifestError("INTEGRATION_CONTENT_INVALID")
        if not _valid_hash(self.preimage_hash) or not _valid_hash(self.planned_postimage_hash):
            raise IntegrationManifestError("INTEGRATION_HASH_INVALID")
        if self.mode is not None and (type(self.mode) is not int or self.mode < 0):
            raise IntegrationManifestError("INTEGRATION_MODE_INVALID")
        if self.destination_path is not None and (
            type(self.destination_path) is not str or not self.destination_path
        ):
            raise IntegrationManifestError("INTEGRATION_DESTINATION_INVALID")
        if self.backup_ref is not None and (type(self.backup_ref) is not str or not self.backup_ref):
            raise IntegrationManifestError("INTEGRATION_BACKUP_REF_INVALID")
        if self.operation in {"create", "replace"} and self.content is None:
            raise IntegrationManifestError("INTEGRATION_CONTENT_REQUIRED")
        if self.operation == "rename" and self.destination_path is None:
            raise IntegrationManifestError("INTEGRATION_DESTINATION_REQUIRED")
        if self.operation == "chmod" and self.mode is None:
            raise IntegrationManifestError("INTEGRATION_MODE_REQUIRED")


@dataclass(frozen=True, slots=True)
class IntegrationManifest:
    entries: tuple[IntegrationEntryPlan, ...]

    def __post_init__(self) -> None:
        if type(self.entries) is not tuple or not self.entries:
            raise IntegrationManifestError("INTEGRATION_ENTRIES_REQUIRED")
        sequences = tuple(entry.sequence for entry in self.entries)
        if len(sequences) != len(frozenset(sequences)):
            raise IntegrationManifestError("INTEGRATION_SEQUENCE_DUPLICATE")
        if sequences != tuple(sorted(sequences)):
            raise IntegrationManifestError("INTEGRATION_SEQUENCE_ORDER_INVALID")
        if not all(type(entry) is IntegrationEntryPlan for entry in self.entries):
            raise IntegrationManifestError("INTEGRATION_ENTRY_INVALID")


__all__ = ["IntegrationEntryPlan", "IntegrationManifest", "IntegrationManifestError"]

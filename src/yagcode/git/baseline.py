"""Immutable dirty-layer baseline data."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from yagcode.git.preflight import IndexEntry


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class BaselineManifest:
    head_tree: str | None
    index_entries: tuple[IndexEntry, ...]
    files: tuple[ManifestEntry, ...]
    ignored_paths: tuple[str, ...]
    protected_snapshot_hash: str


def digest_files(files: dict[str, bytes]) -> tuple[ManifestEntry, ...]:
    return tuple(ManifestEntry(path, hashlib.sha256(value).hexdigest()) for path, value in sorted(files.items()))

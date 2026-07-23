"""Fail-closed platform sandbox contracts with no subprocess fallback."""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


def _is_reparse_directory(path: Path) -> bool:
    """Reject Windows junctions in addition to portable symbolic links."""
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction()) if callable(is_junction) else False


def _absolute_directory(value: Path) -> Path:
    path = Path(value).absolute()
    if path.is_symlink() or _is_reparse_directory(path) or not path.is_dir():
        raise ValueError("SANDBOX_SCOPE_DIRECTORY_INVALID")
    return path.resolve(strict=True)


@dataclass(frozen=True, slots=True)
class DirectoryIdentity:
    device: int
    inode: int


def _directory_identity(path: Path) -> DirectoryIdentity:
    value = os.lstat(path)
    if stat.S_ISLNK(value.st_mode) or _is_reparse_directory(path) or not stat.S_ISDIR(value.st_mode):
        raise ValueError("SANDBOX_SCOPE_DIRECTORY_INVALID")
    return DirectoryIdentity(value.st_dev, value.st_ino)


@dataclass(frozen=True, slots=True)
class SandboxScope:
    shadow_root: Path
    temporary_root: Path
    protected_root: Path
    readonly_runtime_roots: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        roots = (self.shadow_root, self.temporary_root, self.protected_root)
        if any(not isinstance(root, Path) for root in roots):
            raise ValueError("SANDBOX_SCOPE_INVALID")
        for root in roots + self.readonly_runtime_roots:
            _absolute_directory(root)

    def scope_hash(self) -> str:
        payload = [str(_absolute_directory(root)) for root in (
            self.shadow_root,
            self.temporary_root,
            self.protected_root,
            *self.readonly_runtime_roots,
        )]
        return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def scope_failure_hash(scope: SandboxScope) -> str:
    """Stable diagnostic binding for an invalid scope; never resolves its paths."""
    roots = (scope.shadow_root, scope.temporary_root, scope.protected_root, *scope.readonly_runtime_roots)
    return hashlib.sha256(
        json.dumps([str(Path(root).absolute()) for root in roots], separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ScopeSnapshot:
    shadow_root: Path
    temporary_root: Path
    protected_root: Path
    readonly_runtime_roots: tuple[Path, ...]
    identities: tuple[DirectoryIdentity, ...]
    scope_hash: str


def capture_scope_snapshot(scope: SandboxScope) -> ScopeSnapshot:
    roots = (scope.shadow_root, scope.temporary_root, scope.protected_root, *scope.readonly_runtime_roots)
    canonical = tuple(_absolute_directory(root) for root in roots)
    if len(set(canonical)) != len(canonical):
        raise ValueError("SANDBOX_SCOPE_ROOT_OVERLAP")
    writable = canonical[:2]
    protected = canonical[2]
    if any(protected.is_relative_to(root) or root.is_relative_to(protected) for root in writable):
        raise ValueError("SANDBOX_SCOPE_PROTECTED_OVERLAP")
    if any(protected.is_relative_to(root) or root.is_relative_to(protected) for root in canonical[3:]):
        raise ValueError("SANDBOX_RUNTIME_OVERLAPS_PROTECTED")
    identities = tuple(_directory_identity(root) for root in canonical)
    payload = json.dumps([str(root) for root in canonical], separators=(",", ":")).encode()
    return ScopeSnapshot(
        shadow_root=canonical[0],
        temporary_root=canonical[1],
        protected_root=canonical[2],
        readonly_runtime_roots=canonical[3:],
        identities=identities,
        scope_hash=hashlib.sha256(payload).hexdigest(),
    )


def snapshot_is_current(snapshot: ScopeSnapshot) -> bool:
    roots = (
        snapshot.shadow_root,
        snapshot.temporary_root,
        snapshot.protected_root,
        *snapshot.readonly_runtime_roots,
    )
    try:
        return tuple(_directory_identity(root) for root in roots) == snapshot.identities
    except (OSError, ValueError):
        return False


@dataclass(frozen=True, slots=True)
class SandboxAttestation:
    scope_hash: str
    verified: bool
    reason: str
    backend: str = "unknown"
    snapshot: ScopeSnapshot | None = None


def attest_snapshot(snapshot: ScopeSnapshot, *, backend: str) -> SandboxAttestation:
    return SandboxAttestation(snapshot.scope_hash, True, "SANDBOX_VERIFIED", backend, snapshot)


def attestation_is_current(attestation: SandboxAttestation) -> bool:
    return (
        attestation.verified
        and attestation.snapshot is not None
        and attestation.scope_hash == attestation.snapshot.scope_hash
        and snapshot_is_current(attestation.snapshot)
    )


def minimal_environment() -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}


@dataclass(frozen=True, slots=True)
class ProcessRequest:
    executable: str
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not Path(self.executable).is_absolute()
            and not ntpath.isabs(self.executable)
            or "\x00" in self.executable
        ):
            raise ValueError("SANDBOX_EXECUTABLE_ABSOLUTE_REQUIRED")
        if type(self.argv) is not tuple or any(type(value) is not str or "\x00" in value for value in self.argv):
            raise ValueError("SANDBOX_ARGV_INVALID")


@dataclass(slots=True)
class ProcessHandle:
    started: bool
    reason: str
    pid: int | None = None
    _process: object | None = None


@dataclass(frozen=True, slots=True)
class TerminationResult:
    reason: str
    terminated: bool


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    reason: str
    returncode: int | None


class SandboxBackend(Protocol):
    def self_test(self, scope: SandboxScope) -> SandboxAttestation: ...

    def start(self, request: ProcessRequest, attestation: SandboxAttestation) -> ProcessHandle: ...

    def terminate_tree(self, handle: ProcessHandle) -> TerminationResult: ...

    def reconcile(self, handle: ProcessHandle) -> ReconciliationResult: ...


class SandboxRunner:
    """A thin fail-closed facade used by platform implementations and tests."""

    def __init__(self, backend: SandboxBackend) -> None:
        self._backend = backend

    def self_test(self, scope: SandboxScope) -> SandboxAttestation:
        return self._backend.self_test(scope)

    def start(self, request: ProcessRequest, attestation: SandboxAttestation) -> ProcessHandle:
        if not attestation_is_current(attestation):
            return ProcessHandle(False, "SANDBOX_UNAVAILABLE")
        return self._backend.start(request, attestation)

    def terminate_tree(self, handle: ProcessHandle) -> TerminationResult:
        return self._backend.terminate_tree(handle)

    def reconcile(self, handle: ProcessHandle) -> ReconciliationResult:
        return self._backend.reconcile(handle)


__all__ = [
    "ProcessHandle",
    "ProcessRequest",
    "ReconciliationResult",
    "SandboxAttestation",
    "SandboxBackend",
    "SandboxRunner",
    "SandboxScope",
    "ScopeSnapshot",
    "TerminationResult",
    "attestation_is_current",
    "attest_snapshot",
    "capture_scope_snapshot",
    "minimal_environment",
    "snapshot_is_current",
    "scope_failure_hash",
]

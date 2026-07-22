"""Fail-closed, no-follow durable replacement for trusted repository outputs."""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol


@dataclass(frozen=True)
class FileIdentity:
    platform: Literal["posix", "windows"]
    token: tuple[int, ...]


@dataclass(frozen=True)
class LstatSnapshot:
    mode: int
    identity: FileIdentity


class BinaryReadHandle(Protocol):
    def read(self) -> bytes: ...
    def fstat_identity(self) -> FileIdentity: ...
    def close(self) -> None: ...


class BinaryTempHandle(Protocol):
    def write(self, data: bytes) -> int: ...
    def flush(self) -> None: ...
    def fileno(self) -> int: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class StagedFile:
    path: Path
    handle: BinaryTempHandle


class DirectorySyncHandle(Protocol):
    def fstat_identity(self) -> FileIdentity: ...
    def sync_entry(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class ExportOps:
    serializer: Callable[[], bytes]
    lstat: Callable[[Path], LstatSnapshot]
    open_read_no_follow: Callable[[Path], BinaryReadHandle]
    mkdir: Callable[[Path], None]
    temp_factory: Callable[[Path], StagedFile]
    fsync: Callable[[int], None]
    replace: Callable[[Path, Path], None]
    open_parent_no_follow: Callable[[Path], DirectorySyncHandle]
    cleanup: Callable[[Path], None]


class _ReadHandle:
    def __init__(self, fd: int) -> None:
        self._fd = fd
        self._file = os.fdopen(fd, "rb", closefd=False)

    def read(self) -> bytes:
        return self._file.read()

    def fstat_identity(self) -> FileIdentity:
        return _identity_from_stat(os.fstat(self._fd))

    def close(self) -> None:
        self._file.close()
        os.close(self._fd)


class _TempHandle:
    def __init__(self, fd: int) -> None:
        self._fd = fd
        self._file = os.fdopen(fd, "wb", closefd=False)

    def write(self, data: bytes) -> int:
        return self._file.write(data)

    def flush(self) -> None:
        self._file.flush()

    def fileno(self) -> int:
        return self._fd

    def close(self) -> None:
        self._file.close()
        os.close(self._fd)


class _DirectoryHandle:
    def __init__(self, fd: int) -> None:
        self._fd = fd

    def fstat_identity(self) -> FileIdentity:
        return _identity_from_stat(os.fstat(self._fd))

    def sync_entry(self) -> None:
        os.fsync(self._fd)

    def close(self) -> None:
        os.close(self._fd)


def _identity_from_stat(info: os.stat_result) -> FileIdentity:
    if os.name != "posix":
        # The standard library does not expose a no-follow Windows directory
        # handle with a comparable volume/file/reparse identity contract.
        raise OSError("Windows no-follow identity adapter is not provable")
    return FileIdentity("posix", (info.st_dev, info.st_ino))


def _lstat(path: Path) -> LstatSnapshot:
    info = os.lstat(path)
    return LstatSnapshot(info.st_mode, _identity_from_stat(info))


def _open_read_no_follow(path: Path) -> BinaryReadHandle:
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise OSError("no-follow read adapter unavailable")
    return _ReadHandle(os.open(path, os.O_RDONLY | os.O_NOFOLLOW))


def _mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _temp_factory(parent: Path) -> StagedFile:
    fd, raw_path = tempfile.mkstemp(prefix=".schema-", dir=parent)
    return StagedFile(Path(raw_path), _TempHandle(fd))


def _open_parent_no_follow(path: Path) -> DirectorySyncHandle:
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise OSError("no-follow directory adapter unavailable")
    return _DirectoryHandle(os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))


def _cleanup(path: Path) -> None:
    path.unlink(missing_ok=True)


DEFAULT_OPS = ExportOps(
    serializer=lambda: b"",
    lstat=_lstat,
    open_read_no_follow=_open_read_no_follow,
    mkdir=_mkdir,
    temp_factory=_temp_factory,
    fsync=os.fsync,
    replace=os.replace,
    open_parent_no_follow=_open_parent_no_follow,
    cleanup=_cleanup,
)

_LAST_RESIDUAL_STAGING: ContextVar[Path | None] = ContextVar(
    "yagcode_last_residual_staging",
    default=None,
)


def last_residual_staging_path() -> Path | None:
    """Return the exact staged path left behind by the most recent failed cleanup."""

    return _LAST_RESIDUAL_STAGING.get()


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _trusted_target(target: Path, trusted_root: Path) -> tuple[Path, Path]:
    root = _absolute(trusted_root)
    absolute_target = _absolute(target)
    absolute_target.relative_to(root)
    return absolute_target, root


def _regular(snapshot: LstatSnapshot) -> bool:
    return stat.S_ISREG(snapshot.mode)


def _directory(snapshot: LstatSnapshot) -> bool:
    return stat.S_ISDIR(snapshot.mode)


def _parent_chain(parent: Path, root: Path, ops: ExportOps) -> tuple[tuple[Path, LstatSnapshot], ...]:
    relative = parent.relative_to(root)
    snapshots: list[tuple[Path, LstatSnapshot]] = []
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            current = current / part
        snapshot = ops.lstat(current)
        if not _directory(snapshot):
            raise OSError("untrusted parent component")
        snapshots.append((current, snapshot))
    return tuple(snapshots)


def _same_parent_chain(expected: tuple[tuple[Path, LstatSnapshot], ...], ops: ExportOps) -> None:
    for path, prior in expected:
        current = ops.lstat(path)
        if not _directory(current) or current.identity != prior.identity:
            raise OSError("parent identity changed")


def _validate_existing_parent_prefix(parent: Path, root: Path, ops: ExportOps) -> None:
    """Reject an existing symlink/reparse component while allowing a missing output parent."""

    current = root
    for part in (None, *parent.relative_to(root).parts):
        if part is not None:
            current = current / part
        try:
            snapshot = ops.lstat(current)
        except FileNotFoundError:
            return
        if not _directory(snapshot):
            raise OSError("untrusted existing parent component")


@dataclass(frozen=True)
class _TargetState:
    exists: bool
    snapshot: LstatSnapshot | None
    payload: bytes | None
    parent_identity: FileIdentity | None


def read_target_no_follow(target: Path, ops: ExportOps, *, trusted_root: Path) -> _TargetState:
    """Read a regular existing target only after lstat/open/fstat identity agreement."""

    target, root = _trusted_target(target, trusted_root)
    try:
        snapshot = ops.lstat(target)
    except FileNotFoundError:
        _validate_existing_parent_prefix(target.parent, root, ops)
        return _TargetState(False, None, None, None)
    if not _regular(snapshot):
        raise OSError("target is not a regular file")
    parent_chain = _parent_chain(target.parent, root, ops)
    handle = ops.open_read_no_follow(target)
    try:
        if handle.fstat_identity() != snapshot.identity:
            raise OSError("target identity changed while opening")
        payload = handle.read()
    finally:
        handle.close()
    return _TargetState(True, snapshot, payload, parent_chain[-1][1].identity)


def sync_parent_verified(
    parent: Path,
    ops: ExportOps,
    *,
    trusted_root: Path,
    expected_identity: FileIdentity | None = None,
) -> None:
    _, root = _trusted_target(parent / ".parent-sentinel", trusted_root)
    chain = _parent_chain(parent, root, ops)
    parent_identity = chain[-1][1].identity
    if expected_identity is not None and parent_identity != expected_identity:
        raise OSError("parent changed before directory sync")
    handle = ops.open_parent_no_follow(parent)
    try:
        if handle.fstat_identity() != parent_identity:
            raise OSError("parent handle identity changed")
        handle.sync_entry()
    finally:
        handle.close()


def durable_atomic_write(
    target: Path,
    payload: bytes,
    ops: ExportOps,
    *,
    trusted_root: Path,
) -> Literal["DURABLE", "UNCHANGED", "FAILED", "SYNC_UNCONFIRMED"]:
    """Replace once only after durable staging and exact pre-replace revalidation."""

    _LAST_RESIDUAL_STAGING.set(None)

    try:
        target, root = _trusted_target(target, trusted_root)
        initial = read_target_no_follow(target, ops, trusted_root=root)
        if initial.exists and initial.payload == payload:
            if initial.parent_identity is None:
                return "FAILED"
            try:
                sync_parent_verified(
                    target.parent,
                    ops,
                    trusted_root=root,
                    expected_identity=initial.parent_identity,
                )
            except Exception:
                return "SYNC_UNCONFIRMED"
            return "UNCHANGED"
        ops.mkdir(target.parent)
        chain = _parent_chain(target.parent, root, ops)
    except Exception:
        return "FAILED"

    staged: StagedFile | None = None
    cleanup_path: Path | None = None
    staged_closed = False
    replaced = False
    try:
        staged = ops.temp_factory(target.parent)
        staged_path = _absolute(staged.path)
        if staged_path == target:
            raise OSError("staging must not alias target")
        cleanup_path = staged.path
        if staged_path.parent != target.parent:
            raise OSError("staging must be a distinct direct child of parent")
        written = staged.handle.write(payload)
        if written != len(payload):
            raise OSError("short staged write")
        staged.handle.flush()
        ops.fsync(staged.handle.fileno())
        staged.handle.close()
        staged_closed = True

        _same_parent_chain(chain, ops)
        current = read_target_no_follow(target, ops, trusted_root=root)
        if initial.exists != current.exists:
            raise OSError("target existence changed")
        if initial.exists and (
            initial.snapshot is None
            or current.snapshot is None
            or initial.snapshot.identity != current.snapshot.identity
            or initial.payload != current.payload
        ):
            raise OSError("target changed")
        ops.replace(staged.path, target)
        replaced = True
        sync_parent_verified(
            target.parent,
            ops,
            trusted_root=root,
            expected_identity=chain[-1][1].identity,
        )
        return "DURABLE"
    except Exception:
        return "SYNC_UNCONFIRMED" if replaced else "FAILED"
    finally:
        if staged is not None and not replaced:
            if not staged_closed:
                try:
                    staged.handle.close()
                except Exception:
                    pass
            if cleanup_path is not None:
                try:
                    ops.cleanup(cleanup_path)
                except Exception:
                    _LAST_RESIDUAL_STAGING.set(cleanup_path)


__all__ = [
    "BinaryReadHandle", "BinaryTempHandle", "DEFAULT_OPS", "DirectorySyncHandle", "ExportOps",
    "FileIdentity", "LstatSnapshot", "StagedFile", "durable_atomic_write", "last_residual_staging_path", "read_target_no_follow",
    "sync_parent_verified",
]

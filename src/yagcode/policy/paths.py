"""Descriptor-backed trusted write targets.

The public ``ResolvedTarget`` is an identity snapshot, not a reusable path
string.  Every write reopens the authorised directory chain without following
links and compares the snapshot before it changes any byte.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path


class PathSecurityError(RuntimeError):
    """A stable refusal for an unsafe or stale trusted-path operation."""


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    mode_type: int
    reparse_tag: int | None = None

    @classmethod
    def from_stat(cls, value: os.stat_result) -> FileIdentity:
        return cls(value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode))


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    root_identity: FileIdentity
    component_identities: tuple[FileIdentity, ...]
    parent_identity: FileIdentity
    basename: str
    target_identity: FileIdentity | None
    target_type: str | None
    precondition_hash: str | None
    _root: Path
    _canonical_relative_parent: tuple[str, ...]
    _source_path: Path
    _source_component_identities: tuple[FileIdentity, ...]


@dataclass(frozen=True, slots=True)
class PathWriteResult:
    reason: str


def _identity(path: Path) -> FileIdentity:
    return FileIdentity.from_stat(os.lstat(path))


def _file_type(value: os.stat_result) -> str:
    if stat.S_ISREG(value.st_mode):
        return "regular"
    if stat.S_ISDIR(value.st_mode):
        return "directory"
    if stat.S_ISLNK(value.st_mode):
        return "symlink"
    return "other"


def _digest_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    while chunk := os.read(descriptor, 1 << 20):
        digest.update(chunk)
    return digest.hexdigest()


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("UNSAFE_PATH_SHORT_WRITE")
        view = view[written:]


class SecurePathResolver:
    """Resolve a candidate only beneath one non-link trusted root."""

    def __init__(self, root: Path) -> None:
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise PathSecurityError("UNSAFE_PATH_PRIMITIVE_UNAVAILABLE")
        absolute = Path(root).absolute()
        root_stat = os.lstat(absolute)
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise PathSecurityError("UNSAFE_PATH_ROOT_INVALID")
        self._root = absolute.resolve(strict=True)
        self._root_identity = FileIdentity.from_stat(root_stat)

    @property
    def root(self) -> Path:
        return self._root

    def _relative_source(self, candidate: Path) -> tuple[Path, tuple[str, ...]]:
        source = candidate if candidate.is_absolute() else self._root / candidate
        source = source.absolute()
        try:
            relative = source.relative_to(self._root)
        except ValueError as error:
            raise PathSecurityError("UNSAFE_PATH_OUTSIDE_ROOT") from error
        if not relative.parts:
            raise PathSecurityError("UNSAFE_PATH_ROOT_TARGET")
        if any(component in {".", ".."} for component in relative.parts):
            raise PathSecurityError("UNSAFE_PATH_COMPONENT_INVALID")
        return source, relative.parts

    def _open_parent(self, parent_parts: tuple[str, ...]) -> tuple[int, tuple[FileIdentity, ...]]:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(self._root, flags)
        identities = [FileIdentity.from_stat(os.fstat(descriptor))]
        try:
            for component in parent_parts:
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
                identities.append(FileIdentity.from_stat(os.fstat(descriptor)))
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor, tuple(identities)

    def resolve_for_write(self, candidate: Path) -> ResolvedTarget:
        source, source_parts = self._relative_source(candidate)
        source_identities: list[FileIdentity] = [_identity(self._root)]
        current = self._root
        for index, component in enumerate(source_parts):
            current = current / component
            try:
                snapshot = os.lstat(current)
            except FileNotFoundError:
                if index == len(source_parts) - 1:
                    break
                raise
            if stat.S_ISLNK(snapshot.st_mode):
                raise PathSecurityError("UNSAFE_PATH_SYMLINK_COMPONENT")
            source_identities.append(FileIdentity.from_stat(snapshot))

        canonical = source.resolve(strict=False)
        try:
            relative = canonical.relative_to(self._root)
        except ValueError as error:
            raise PathSecurityError("UNSAFE_PATH_OUTSIDE_ROOT") from error
        if not relative.parts:
            raise PathSecurityError("UNSAFE_PATH_ROOT_TARGET")
        parent_parts = relative.parts[:-1]
        descriptor, identities = self._open_parent(parent_parts)
        try:
            parent_identity = FileIdentity.from_stat(os.fstat(descriptor))
            try:
                target_stat = os.lstat(relative.parts[-1], dir_fd=descriptor)
            except FileNotFoundError:
                target_identity = None
                target_type = None
                precondition_hash = None
            else:
                if stat.S_ISLNK(target_stat.st_mode) or not stat.S_ISREG(target_stat.st_mode):
                    raise PathSecurityError("UNSAFE_PATH_TARGET_TYPE")
                if target_stat.st_nlink != 1:
                    raise PathSecurityError("UNSAFE_PATH_HARDLINK_TARGET")
                target_identity = FileIdentity.from_stat(target_stat)
                target_type = _file_type(target_stat)
                target_fd = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
                try:
                    precondition_hash = _digest_descriptor(target_fd)
                finally:
                    os.close(target_fd)
        finally:
            os.close(descriptor)
        return ResolvedTarget(
            root_identity=self._root_identity,
            component_identities=identities,
            parent_identity=parent_identity,
            basename=relative.parts[-1],
            target_identity=target_identity,
            target_type=target_type,
            precondition_hash=precondition_hash,
            _root=self._root,
            _canonical_relative_parent=parent_parts,
            _source_path=source,
            _source_component_identities=tuple(source_identities),
        )


class SecurePathDispatcher:
    """Write only through a freshly revalidated directory descriptor."""

    def __init__(self, resolver: SecurePathResolver) -> None:
        self._resolver = resolver

    def _source_is_current(self, target: ResolvedTarget) -> bool:
        try:
            parts = target._source_path.relative_to(target._root).parts
            current = target._root
            observed = [_identity(current)]
            for index, component in enumerate(parts):
                current = current / component
                try:
                    observed.append(_identity(current))
                except FileNotFoundError:
                    if index == len(parts) - 1 and target.target_identity is None:
                        break
                    return False
        except (FileNotFoundError, ValueError, OSError):
            return False
        return tuple(observed) == target._source_component_identities

    def write(self, target: ResolvedTarget, content: bytes) -> PathWriteResult:
        if type(target) is not ResolvedTarget or type(content) is not bytes:
            return PathWriteResult("UNSAFE_PATH_ARGUMENT_INVALID")
        if _identity(target._root) != target.root_identity or not self._source_is_current(target):
            return PathWriteResult("STALE_TARGET")
        try:
            descriptor, identities = self._resolver._open_parent(target._canonical_relative_parent)
        except (FileNotFoundError, OSError, PathSecurityError):
            return PathWriteResult("STALE_TARGET")
        try:
            if identities != target.component_identities or FileIdentity.from_stat(os.fstat(descriptor)) != target.parent_identity:
                return PathWriteResult("STALE_TARGET")
            try:
                existing = os.lstat(target.basename, dir_fd=descriptor)
            except FileNotFoundError:
                if target.target_identity is not None:
                    return PathWriteResult("STALE_TARGET")
                fd = os.open(
                    target.basename,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=descriptor,
                )
                try:
                    _write_all(fd, content)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                return PathWriteResult("WRITTEN")
            if target.target_identity is None or not stat.S_ISREG(existing.st_mode):
                return PathWriteResult("STALE_TARGET")
            fd = os.open(target.basename, os.O_RDWR | os.O_NOFOLLOW, dir_fd=descriptor)
            try:
                current = os.fstat(fd)
                if FileIdentity.from_stat(current) != target.target_identity or current.st_nlink != 1:
                    return PathWriteResult("STALE_TARGET")
                current_hash = _digest_descriptor(fd)
                if current_hash != target.precondition_hash:
                    return PathWriteResult("STALE_TARGET")
                os.ftruncate(fd, 0)
                os.lseek(fd, 0, os.SEEK_SET)
                _write_all(fd, content)
                os.fsync(fd)
            finally:
                os.close(fd)
            return PathWriteResult("WRITTEN")
        except OSError:
            return PathWriteResult("STALE_TARGET")
        finally:
            os.close(descriptor)


__all__ = [
    "FileIdentity",
    "PathSecurityError",
    "PathWriteResult",
    "ResolvedTarget",
    "SecurePathDispatcher",
    "SecurePathResolver",
]

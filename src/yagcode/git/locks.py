"""Project locks keyed by canonical repository identities and write roots."""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from pathlib import Path


class ProjectLockError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _normalise(path: Path) -> Path:
    return Path(path).resolve(strict=False)


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


@dataclass(slots=True)
class ProjectLease:
    _registry: "ProjectLockRegistry"
    _roots: tuple[Path, ...]
    _paths: tuple[Path, ...] = ()

    def release(self) -> None:
        self._registry._release(self._roots, self._paths)


class ProjectLockRegistry:
    def __init__(self, lock_dir: Path | None = None) -> None:
        self._held: set[Path] = set()
        self._lock_dir = Path(lock_dir) if lock_dir is not None else None
        self._owner = secrets.token_hex(16)

    def acquire(self, write_roots: tuple[Path, ...], repository_roots: tuple[Path, ...]) -> ProjectLease:
        roots = tuple(dict.fromkeys(_normalise(path) for path in write_roots + repository_roots))
        if not roots:
            raise ProjectLockError("PROJECT_LOCK_ROOTS_REQUIRED")
        if any(_overlaps(candidate, held) for candidate in roots for held in self._held):
            raise ProjectLockError("PROJECT_LOCK_OVERLAP")
        paths: tuple[Path, ...] = ()
        if self._lock_dir is not None:
            paths = self._acquire_persistent(roots)
        self._held.update(roots)
        return ProjectLease(self, roots, paths)

    def _acquire_persistent(self, roots: tuple[Path, ...]) -> tuple[Path, ...]:
        assert self._lock_dir is not None
        self._lock_dir.mkdir(parents=True, exist_ok=True)
        existing = self._read_persistent_roots()
        if any(_overlaps(candidate, held) for candidate in roots for held in existing):
            raise ProjectLockError("PROJECT_LOCK_OVERLAP")
        created: list[Path] = []
        try:
            for root in roots:
                digest = hashlib.sha256(os.fspath(root).encode("utf-8")).hexdigest()
                path = self._lock_dir / f"{digest}.lock"
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                    file.write(f"{self._owner}\n{root}\n")
                created.append(path)
        except FileExistsError as error:
            for path in reversed(created):
                path.unlink(missing_ok=True)
            raise ProjectLockError("PROJECT_LOCK_OVERLAP") from error
        except BaseException:
            for path in reversed(created):
                path.unlink(missing_ok=True)
            raise
        return tuple(created)

    def _read_persistent_roots(self) -> tuple[Path, ...]:
        assert self._lock_dir is not None
        roots: list[Path] = []
        for path in sorted(self._lock_dir.glob("*.lock")):
            try:
                owner, raw_root = path.read_text(encoding="utf-8").splitlines()[:2]
            except (OSError, ValueError):
                raise ProjectLockError("PROJECT_LOCK_CORRUPT") from None
            if owner == self._owner:
                continue
            roots.append(Path(raw_root))
        return tuple(roots)

    def _release(self, roots: tuple[Path, ...], paths: tuple[Path, ...]) -> None:
        self._held.difference_update(roots)
        for path in paths:
            path.unlink(missing_ok=True)

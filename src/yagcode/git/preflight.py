"""Deterministic refusals before any private shadow is created."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from yagcode.git.identity import RepositoryIdentity, discover_repository, run_git


class GitPreflightError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class IndexEntry:
    mode: str
    object_id: str
    stage: int
    path: str


def read_index_entries(root: Path) -> tuple[IndexEntry, ...]:
    output = run_git(root, "ls-files", "--stage", "-z").stdout
    entries: list[IndexEntry] = []
    for record in output.split("\0"):
        if not record:
            continue
        metadata, path = record.split("\t", 1)
        mode, object_id, stage = metadata.split()
        entries.append(IndexEntry(mode, object_id, int(stage), path))
    return tuple(entries)


def ensure_stage_zero_only(entries: tuple[IndexEntry, ...]) -> None:
    if any(entry.stage != 0 for entry in entries):
        raise GitPreflightError("UNMERGED_INDEX_UNSUPPORTED")


def ensure_no_submodules(entries: tuple[IndexEntry, ...]) -> None:
    if any(entry.mode == "160000" for entry in entries):
        raise GitPreflightError("SUBMODULE_UNSUPPORTED")


def ensure_no_alternates(identity: RepositoryIdentity) -> None:
    alternates = identity.common_dir / "objects" / "info" / "alternates"
    if alternates.exists():
        raise GitPreflightError("GIT_ALTERNATES_UNSUPPORTED")


def preflight_repository(root: Path) -> RepositoryIdentity:
    identity = discover_repository(root)
    ensure_no_alternates(identity)
    sparse = run_git(identity.worktree_root, "config", "--bool", "core.sparseCheckout", check=False)
    if sparse.returncode == 0 and sparse.stdout.strip().lower() == "true":
        raise GitPreflightError("SPARSE_CHECKOUT_UNSUPPORTED")
    lfs = run_git(identity.worktree_root, "config", "--bool", "filter.lfs.required", check=False)
    if lfs.returncode == 0 and lfs.stdout.strip().lower() == "true":
        raise GitPreflightError("LFS_AUTOMATIC_MANAGEMENT_UNSUPPORTED")
    entries = read_index_entries(identity.worktree_root)
    ensure_stage_zero_only(entries)
    ensure_no_submodules(entries)
    return identity

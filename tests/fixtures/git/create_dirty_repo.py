"""Test-owned Git repository oracle; it deliberately imports no production code."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


def git(root: Path, *argv: str) -> str:
    result = subprocess.run(
        ["git", "-C", os.fspath(root), *argv], check=True, text=True, capture_output=True
    )
    return result.stdout


def tree_files(root: Path) -> dict[str, bytes]:
    return {
        os.fspath(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }


@dataclass(frozen=True, slots=True)
class DirtyRepo:
    root: Path
    head_tree: str
    stage_zero_index: tuple[tuple[str, str], ...]
    tracked_worktree: dict[str, bytes]
    untracked_nonignored: dict[str, bytes]

    def protected_snapshot(self) -> tuple[str, str, str, str]:
        common = Path(git(self.root, "rev-parse", "--git-common-dir").strip()).resolve()
        if not common.is_absolute():
            common = (self.root / common).resolve()
        common_digest = hashlib.sha256()
        for path in sorted(common.rglob("*")):
            if path.is_file():
                common_digest.update(os.fspath(path.relative_to(common)).encode())
                common_digest.update(path.read_bytes())
        worktree_digest = hashlib.sha256()
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and ".git" not in path.parts:
                worktree_digest.update(os.fspath(path.relative_to(self.root)).encode())
                worktree_digest.update(path.read_bytes())
        return (
            git(self.root, "status", "--porcelain=v1"),
            git(self.root, "rev-parse", "HEAD"),
            common_digest.hexdigest(),
            worktree_digest.hexdigest(),
        )


def create_dirty_repo(root: Path) -> DirtyRepo:
    root.mkdir(parents=True)
    git(root, "init")
    git(root, "config", "user.name", "test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "tracked.txt").write_text("head\n")
    (root / ".gitignore").write_text("ignored.txt\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "initial")
    (root / "tracked.txt").write_text("worktree\n")
    (root / "staged.txt").write_text("index\n")
    git(root, "add", "staged.txt")
    (root / "untracked.txt").write_text("untracked\n")
    (root / "ignored.txt").write_text("ignored\n")
    entries = tuple(
        (line.split()[1], line.split()[3])
        for line in git(root, "ls-files", "--stage").splitlines()
    )
    tracked = {name: (root / name).read_bytes() for _, name in entries if (root / name).exists()}
    return DirtyRepo(
        root=root,
        head_tree=git(root, "rev-parse", "HEAD^{tree}").strip(),
        stage_zero_index=entries,
        tracked_worktree=tracked,
        untracked_nonignored={"untracked.txt": b"untracked\n"},
    )


def assert_dirty_oracle_detects_layer_mutation(repo: DirtyRepo) -> None:
    assert repo.head_tree
    assert repo.stage_zero_index
    assert repo.tracked_worktree["tracked.txt"] == b"worktree\n"
    assert repo.untracked_nonignored == {"untracked.txt": b"untracked\n"}

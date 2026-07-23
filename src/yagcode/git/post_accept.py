"""Post-accept local commit creation using an isolated temporary index."""

from __future__ import annotations

import os
import subprocess
import tempfile

from dataclasses import dataclass
from pathlib import Path

from yagcode.git.conventional_commit import is_conventional_commit
from yagcode.git.identity import git_environment, run_git


@dataclass(frozen=True, slots=True)
class PostAcceptCommitResult:
    state: str
    commit_oid: str | None = None
    reason_code: str | None = None


def _safe_paths(paths: tuple[str, ...]) -> bool:
    return bool(paths) and all(
        type(path) is str
        and path
        and not path.startswith("/")
        and "\\" not in path
        and all(part not in {"", ".", "..", ".git"} for part in path.split("/"))
        for path in paths
    )


class PostAcceptCommitter:
    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve(strict=True)

    def commit_agent_delta(
        self,
        *,
        message: str,
        paths: tuple[str, ...],
        ref: str = "refs/yagcode/accepted/latest",
        author_name: str = "YagCode",
        author_email: str = "yagcode@example.invalid",
    ) -> PostAcceptCommitResult:
        if not is_conventional_commit(message):
            return PostAcceptCommitResult("REJECTED", reason_code="COMMIT_MESSAGE_INVALID")
        if not _safe_paths(paths):
            return PostAcceptCommitResult("REJECTED", reason_code="COMMIT_PATHS_INVALID")
        head = run_git(self._root, "rev-parse", "HEAD").stdout.strip()
        with tempfile.TemporaryDirectory(prefix="yagcode-index-") as temp:
            index_file = Path(temp) / "index"
            env = git_environment()
            env["GIT_INDEX_FILE"] = os.fspath(index_file)
            _run_git(self._root, "read-tree", head, env=env)
            _run_git(self._root, "add", "--", *paths, env=env)
            if _run_git(self._root, "diff", "--cached", "--quiet", env=env, check=False).returncode == 0:
                return PostAcceptCommitResult("REJECTED", reason_code="COMMIT_EMPTY_DELTA")
            tree = _run_git(self._root, "write-tree", env=env).stdout.strip()
            commit = _run_git(
                self._root,
                "-c",
                f"user.name={author_name}",
                "-c",
                f"user.email={author_email}",
                "commit-tree",
                tree,
                "-p",
                head,
                "-m",
                message,
                env=env,
            ).stdout.strip()
        existing = run_git(self._root, "rev-parse", "--verify", ref, check=False)
        if existing.returncode == 0:
            run_git(self._root, "update-ref", ref, commit, existing.stdout.strip())
        else:
            run_git(self._root, "update-ref", ref, commit)
        return PostAcceptCommitResult("COMMITTED", commit_oid=commit)


def _run_git(
    root: Path,
    *argv: str,
    env: dict[str, str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", os.fspath(root), *argv],
        check=check,
        capture_output=True,
        text=True,
        env=env,
        shell=False,
    )


__all__ = ["PostAcceptCommitResult", "PostAcceptCommitter"]

"""Repository discovery using a scrubbed, argv-only Git invocation."""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from yagcode.policy.paths import FileIdentity


class GitIdentityError(RuntimeError):
    """A repository path cannot safely be identified."""


def git_environment() -> dict[str, str]:
    """Return the minimal environment accepted by every Git subprocess."""
    allowed = {"HOME", "PATH", "SystemRoot", "TEMP", "TMP"}
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PAGER": "cat",
            "GIT_EDITOR": ":",
            "GIT_ASKPASS": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    return environment


def run_git(root: Path, *argv: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", os.fspath(root), *argv],
        check=check,
        capture_output=True,
        text=True,
        env=git_environment(),
        shell=False,
    )


def _file_identity(path: Path) -> FileIdentity:
    result = os.lstat(path)
    if stat.S_ISLNK(result.st_mode):
        raise GitIdentityError("REPOSITORY_SYMLINK_UNSUPPORTED")
    return FileIdentity.from_stat(result)


@dataclass(frozen=True, slots=True)
class RepositoryIdentity:
    worktree_root: Path
    common_dir: Path
    worktree_file_id: FileIdentity
    common_dir_file_id: FileIdentity


def discover_repository(path: Path) -> RepositoryIdentity:
    candidate = Path(path).resolve(strict=True)
    try:
        worktree = Path(run_git(candidate, "rev-parse", "--show-toplevel").stdout.strip()).resolve(strict=True)
        common_raw = Path(run_git(candidate, "rev-parse", "--git-common-dir").stdout.strip())
    except (OSError, subprocess.CalledProcessError) as error:
        raise GitIdentityError("GIT_REPOSITORY_REQUIRED") from error
    common = common_raw if common_raw.is_absolute() else (candidate / common_raw)
    common = common.resolve(strict=True)
    return RepositoryIdentity(worktree, common, _file_identity(worktree), _file_identity(common))

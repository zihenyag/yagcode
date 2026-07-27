"""Read-only working-tree inspection for the desktop workbench."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from yagcode.git.identity import run_git


DiffLineKind = Literal["context", "add", "delete", "hunk"]
DiffFileStatus = Literal["modified", "added", "deleted"]


@dataclass(frozen=True, slots=True)
class WorktreeDiffLine:
    kind: DiffLineKind
    old_line: int | None
    new_line: int | None
    content: str


@dataclass(frozen=True, slots=True)
class WorktreeDiffFile:
    path: str
    status: DiffFileStatus
    additions: int
    deletions: int
    lines: tuple[WorktreeDiffLine, ...]


@dataclass(frozen=True, slots=True)
class ProjectInspection:
    path: str
    label: str
    exists: bool
    is_directory: bool
    is_git_repo: bool
    git_root: str | None
    branch: str | None
    status_summary: tuple[str, ...]
    diff_files: tuple[WorktreeDiffFile, ...]
    error: str | None = None


_HUNK_RE = re.compile(r"^@@ -(?P<old>\d+)(?:,\d+)? \+(?P<new>\d+)(?:,\d+)? @@")


def inspect_project(path_text: str) -> ProjectInspection:
    """Inspect a local project without mutating it."""

    path = Path(path_text).expanduser()
    label = path.name or "当前项目"
    if not path.exists():
        return ProjectInspection(
            path=str(path),
            label=label,
            exists=False,
            is_directory=False,
            is_git_repo=False,
            git_root=None,
            branch=None,
            status_summary=(),
            diff_files=(),
            error="PROJECT_PATH_NOT_FOUND",
        )
    if not path.is_dir():
        return ProjectInspection(
            path=str(path),
            label=label,
            exists=True,
            is_directory=False,
            is_git_repo=False,
            git_root=None,
            branch=None,
            status_summary=(),
            diff_files=(),
            error="PROJECT_PATH_NOT_DIRECTORY",
        )
    try:
        git_root = run_git(path, "rev-parse", "--show-toplevel").stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ProjectInspection(
            path=str(path),
            label=label,
            exists=True,
            is_directory=True,
            is_git_repo=False,
            git_root=None,
            branch=None,
            status_summary=(),
            diff_files=(),
            error=None,
        )

    branch = _branch_for(path)
    status_summary = tuple(
        line for line in run_git(path, "status", "--short", "--branch").stdout.splitlines() if line
    )
    diff_text = run_git(
        path,
        "-c",
        "core.hooksPath=/dev/null",
        "diff",
        "--no-ext-diff",
        "--unified=3",
        "HEAD",
        "--",
    ).stdout
    return ProjectInspection(
        path=str(path),
        label=label,
        exists=True,
        is_directory=True,
        is_git_repo=True,
        git_root=git_root,
        branch=branch,
        status_summary=status_summary,
        diff_files=parse_unified_diff(diff_text),
        error=None,
    )


def parse_unified_diff(diff_text: str) -> tuple[WorktreeDiffFile, ...]:
    files: list[WorktreeDiffFile] = []
    current_path: str | None = None
    current_status: DiffFileStatus = "modified"
    current_lines: list[WorktreeDiffLine] = []
    old_line: int | None = None
    new_line: int | None = None

    def flush() -> None:
        nonlocal current_path, current_status, current_lines
        if current_path is None:
            return
        additions = sum(1 for line in current_lines if line.kind == "add")
        deletions = sum(1 for line in current_lines if line.kind == "delete")
        files.append(
            WorktreeDiffFile(
                path=current_path,
                status=current_status,
                additions=additions,
                deletions=deletions,
                lines=tuple(current_lines),
            )
        )
        current_path = None
        current_status = "modified"
        current_lines = []

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            flush()
            current_path = _path_from_diff_header(raw_line)
            current_status = "modified"
            old_line = None
            new_line = None
            continue
        if current_path is None:
            continue
        if raw_line.startswith("new file mode"):
            current_status = "added"
            continue
        if raw_line.startswith("deleted file mode"):
            current_status = "deleted"
            continue
        if raw_line.startswith("+++ b/"):
            current_path = raw_line.removeprefix("+++ b/")
            continue
        if raw_line.startswith("@@ "):
            match = _HUNK_RE.match(raw_line)
            old_line = int(match.group("old")) if match is not None else None
            new_line = int(match.group("new")) if match is not None else None
            current_lines.append(WorktreeDiffLine("hunk", None, None, raw_line))
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            current_lines.append(WorktreeDiffLine("add", None, new_line, raw_line[1:]))
            if new_line is not None:
                new_line += 1
            continue
        if raw_line.startswith("-") and not raw_line.startswith("---"):
            current_lines.append(WorktreeDiffLine("delete", old_line, None, raw_line[1:]))
            if old_line is not None:
                old_line += 1
            continue
        if raw_line.startswith(" "):
            current_lines.append(WorktreeDiffLine("context", old_line, new_line, raw_line[1:]))
            if old_line is not None:
                old_line += 1
            if new_line is not None:
                new_line += 1

    flush()
    return tuple(files)


def _path_from_diff_header(line: str) -> str:
    parts = line.split(" ")
    if len(parts) >= 4 and parts[3].startswith("b/"):
        return parts[3][2:]
    return "unknown"


def _branch_for(path: Path) -> str | None:
    branch = run_git(path, "branch", "--show-current", check=False).stdout.strip()
    if branch:
        return branch
    commit = run_git(path, "rev-parse", "--short", "HEAD", check=False).stdout.strip()
    return commit or None


__all__ = [
    "ProjectInspection",
    "WorktreeDiffFile",
    "WorktreeDiffLine",
    "inspect_project",
    "parse_unified_diff",
]

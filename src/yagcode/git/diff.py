"""Generate candidate diffs without external drivers or prompts."""

from __future__ import annotations

from pathlib import Path

from yagcode.git.identity import run_git


def candidate_diff(shadow_worktree: Path) -> str:
    return run_git(shadow_worktree, "-c", "core.hooksPath=/dev/null", "diff", "--no-ext-diff", "--binary", "HEAD", "--").stdout

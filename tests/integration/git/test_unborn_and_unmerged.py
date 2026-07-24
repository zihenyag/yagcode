from __future__ import annotations

import importlib
from pathlib import Path

from tests.fixtures.git.create_dirty_repo import git, run_git


def create_unmerged_repo(root: Path) -> Path:
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    (root / "tracked.txt").write_bytes(b"base\n")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-m", "base")
    git(root, "switch", "-c", "ours")
    (root / "tracked.txt").write_bytes(b"ours\n")
    git(root, "commit", "-am", "ours")
    git(root, "switch", "-c", "theirs", "HEAD~1")
    (root / "tracked.txt").write_bytes(b"theirs\n")
    git(root, "commit", "-am", "theirs")
    merge = run_git(root, "merge", "ours", check=False)
    assert merge.returncode != 0
    return root


def test_owned_unmerged_fixture_has_nonzero_stages(tmp_path: Path) -> None:
    root = create_unmerged_repo(tmp_path / "repo")
    stages = {line.split()[2] for line in git(root, "ls-files", "--stage").splitlines()}
    assert stages == {"1", "2", "3"}


def test_unborn_repository_uses_a_private_synthetic_run_ref(tmp_path: Path) -> None:
    root = tmp_path / "unborn"
    root.mkdir()
    git(root, "init")
    (root / "draft.txt").write_bytes(b"draft\n")
    git(root, "add", "draft.txt")
    shadow = importlib.import_module("yagcode.git.shadow")
    baseline = shadow.ShadowService(tmp_path / "private").capture_and_create(root, run_id="unborn")
    assert baseline.shadow_head_tree is None
    assert git(baseline.shadow_root / "worktree", "rev-parse", "refs/yagcode/runs/unborn")


def test_unmerged_index_is_refused_before_shadow_creation(tmp_path: Path) -> None:
    root = create_unmerged_repo(tmp_path / "repo")
    shadow = importlib.import_module("yagcode.git.shadow")
    try:
        shadow.ShadowService(tmp_path / "private").capture_and_create(root, run_id="x")
    except shadow.GitPreflightError as error:
        assert error.reason_code == "UNMERGED_INDEX_UNSUPPORTED"
    else:
        raise AssertionError("unmerged index was accepted")
    assert not (tmp_path / "private" / "x").exists()

from __future__ import annotations

import importlib

from pathlib import Path

from tests.fixtures.git.create_dirty_repo import assert_dirty_oracle_detects_layer_mutation, create_dirty_repo
from tests.fixtures.git.create_dirty_repo import git


def test_owned_dirty_oracle(tmp_path: Path) -> None:
    repo = create_dirty_repo(tmp_path / "repo")
    assert_dirty_oracle_detects_layer_mutation(repo)


def test_owned_dirty_oracle_rejects_layer_mutation(tmp_path: Path) -> None:
    repo = create_dirty_repo(tmp_path / "repo")
    assert repo.tracked_worktree != {"tracked.txt": b"head\n"}
    assert repo.untracked_nonignored != {}


def test_shadow_reproduces_dirty_layers_without_touching_real_git(tmp_path: Path) -> None:
    dirty_repo = create_dirty_repo(tmp_path / "repo")
    before = dirty_repo.protected_snapshot()
    shadow = importlib.import_module("yagcode.git.shadow")
    baseline = shadow.ShadowService(tmp_path / "application-private").capture_and_create(
        dirty_repo.root, run_id="run-1"
    )
    assert baseline.shadow_head_tree == dirty_repo.head_tree
    assert baseline.shadow_index == dirty_repo.stage_zero_index
    assert baseline.shadow_worktree == dirty_repo.tracked_worktree | dirty_repo.untracked_nonignored
    assert baseline.manifest == dirty_repo.tracked_worktree | dirty_repo.untracked_nonignored
    assert dirty_repo.protected_snapshot() == before


def test_shadow_diff_can_read_index_only_staged_blobs(tmp_path: Path) -> None:
    dirty_repo = create_dirty_repo(tmp_path / "repo")
    shadow = importlib.import_module("yagcode.git.shadow")
    diff = importlib.import_module("yagcode.git.diff")

    baseline = shadow.ShadowService(tmp_path / "application-private").capture_and_create(
        dirty_repo.root, run_id="run-diff"
    )
    candidate = diff.candidate_diff(baseline.shadow_root / "worktree")

    assert "staged.txt" in candidate
    assert "index" in candidate


def test_shadow_uses_linked_worktree_private_index(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    (root / "tracked.txt").write_bytes(b"head\n")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-m", "initial")
    linked = tmp_path / "linked"
    git(root, "worktree", "add", str(linked), "-b", "linked-branch")
    (linked / "linked-staged.txt").write_bytes(b"linked index\n")
    git(linked, "add", "linked-staged.txt")

    shadow = importlib.import_module("yagcode.git.shadow")
    diff = importlib.import_module("yagcode.git.diff")
    baseline = shadow.ShadowService(tmp_path / "private").capture_and_create(linked, run_id="linked")
    candidate = diff.candidate_diff(baseline.shadow_root / "worktree")

    assert "linked-staged.txt" in candidate
    assert "linked index" in candidate

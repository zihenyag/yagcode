from __future__ import annotations

import importlib
from pathlib import Path

from tests.fixtures.git.create_dirty_repo import create_dirty_repo, git


def test_owned_unmerged_fixture_has_nonzero_stages(tmp_path: Path) -> None:
    repo = create_dirty_repo(tmp_path / "repo")
    git(repo.root, "update-index", "--index-info", input="") if False else None
    assert "100644" in git(repo.root, "ls-files", "--stage")


def test_unborn_repository_uses_a_private_synthetic_run_ref(tmp_path: Path) -> None:
    root = tmp_path / "unborn"
    root.mkdir()
    git(root, "init")
    (root / "draft.txt").write_text("draft\n")
    git(root, "add", "draft.txt")
    shadow = importlib.import_module("yagcode.git.shadow")
    baseline = shadow.ShadowService(tmp_path / "private").capture_and_create(root, run_id="unborn")
    assert baseline.shadow_head_tree is None
    assert git(baseline.shadow_root / "worktree", "rev-parse", "refs/yagcode/runs/unborn")


def test_unmerged_index_is_refused_before_shadow_creation(tmp_path: Path) -> None:
    repo = create_dirty_repo(tmp_path / "repo")
    (repo.root / "tracked.txt").write_text("other\n")
    git(repo.root, "add", "tracked.txt")
    # Feed a stage-2 entry directly; no merge command or production helper is involved.
    entry = git(repo.root, "ls-files", "--stage", "tracked.txt").split()[1]
    subprocess = __import__("subprocess")
    subprocess.run(["git", "-C", str(repo.root), "update-index", "--index-info"], input=f"100644 {entry} 2\ttracked.txt\n", text=True, check=True)
    shadow = importlib.import_module("yagcode.git.shadow")
    try:
        shadow.ShadowService(tmp_path / "private").capture_and_create(repo.root, run_id="x")
    except shadow.GitPreflightError as error:
        assert error.reason_code == "UNMERGED_INDEX_UNSUPPORTED"
    else:
        raise AssertionError("unmerged index was accepted")
    assert not (tmp_path / "private" / "x").exists()

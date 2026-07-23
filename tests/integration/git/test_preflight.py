from __future__ import annotations

import importlib
from pathlib import Path

from tests.fixtures.git.create_dirty_repo import create_dirty_repo, git


def test_owned_preflight_fixture_is_a_real_repository(tmp_path: Path) -> None:
    repo = create_dirty_repo(tmp_path / "repo")
    assert git(repo.root, "rev-parse", "--is-inside-work-tree").strip() == "true"


def test_preflight_resolves_identity_and_rejects_sparse_checkout(tmp_path: Path) -> None:
    repo = create_dirty_repo(tmp_path / "repo")
    git(repo.root, "sparse-checkout", "init", "--no-cone")
    preflight = importlib.import_module("yagcode.git.preflight")
    try:
        preflight.preflight_repository(repo.root)
    except preflight.GitPreflightError as error:
        assert error.reason_code == "SPARSE_CHECKOUT_UNSUPPORTED"
    else:
        raise AssertionError("sparse checkout was accepted")


def test_preflight_rejects_git_alternates_before_shadow_creation(tmp_path: Path) -> None:
    repo = create_dirty_repo(tmp_path / "repo")
    common = Path(git(repo.root, "rev-parse", "--git-common-dir").strip())
    if not common.is_absolute():
        common = repo.root / common
    alternates = common / "objects" / "info" / "alternates"
    alternates.parent.mkdir(parents=True, exist_ok=True)
    alternates.write_text(str(tmp_path / "other-objects"), encoding="utf-8")
    preflight = importlib.import_module("yagcode.git.preflight")

    try:
        preflight.preflight_repository(repo.root)
    except preflight.GitPreflightError as error:
        assert error.reason_code == "GIT_ALTERNATES_UNSUPPORTED"
    else:
        raise AssertionError("alternates were accepted")


def test_preflight_rejects_submodule_gitlink_index_entries(tmp_path: Path) -> None:
    repo = create_dirty_repo(tmp_path / "repo")
    commit_id = git(repo.root, "rev-parse", "HEAD").strip()
    git(repo.root, "update-index", "--add", "--cacheinfo", "160000", commit_id, "vendor/sub")
    preflight = importlib.import_module("yagcode.git.preflight")

    try:
        preflight.preflight_repository(repo.root)
    except preflight.GitPreflightError as error:
        assert error.reason_code == "SUBMODULE_UNSUPPORTED"
    else:
        raise AssertionError("submodule gitlink was accepted")

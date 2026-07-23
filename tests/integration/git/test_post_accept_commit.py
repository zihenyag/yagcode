from __future__ import annotations

import importlib
import os
import subprocess

from pathlib import Path


def git(root: Path, *argv: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", os.fspath(root), *argv],
        check=True,
        text=True,
        capture_output=True,
        env=env,
        shell=False,
    )
    return result.stdout


def make_repo(root: Path) -> Path:
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "src").mkdir()
    (root / "src" / "agent.py").write_text("old\n")
    (root / "src" / "user.py").write_text("user\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "initial")
    return root


def test_owned_temporary_index_fixture_preserves_real_index(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    before_index = git(repo, "status", "--porcelain=v1")
    (repo / "src" / "agent.py").write_text("agent\n")
    (repo / "src" / "user.py").write_text("dirty user\n")
    assert git(repo, "status", "--porcelain=v1") != before_index
    assert git(repo, "diff", "--", "src/user.py")


def test_commit_uses_temporary_index_with_only_agent_delta(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    (repo / "src" / "agent.py").write_text("agent\n")
    (repo / "src" / "user.py").write_text("dirty user\n")
    index_before = git(repo, "diff", "--cached")
    worktree_user_before = (repo / "src" / "user.py").read_text()

    post_accept = importlib.import_module("yagcode.git.post_accept")
    result = post_accept.PostAcceptCommitter(repo).commit_agent_delta(
        message="fix(core): preserve user changes",
        paths=("src/agent.py",),
    )

    assert result.state == "COMMITTED"
    assert git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", result.commit_oid).splitlines() == [
        "src/agent.py"
    ]
    assert git(repo, "diff", "--cached") == index_before
    assert (repo / "src" / "user.py").read_text() == worktree_user_before


def test_invalid_conventional_commit_message_is_rejected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    (repo / "src" / "agent.py").write_text("agent\n")
    post_accept = importlib.import_module("yagcode.git.post_accept")

    result = post_accept.PostAcceptCommitter(repo).commit_agent_delta(
        message="update stuff",
        paths=("src/agent.py",),
    )

    assert result.state == "REJECTED"
    assert result.reason_code == "COMMIT_MESSAGE_INVALID"

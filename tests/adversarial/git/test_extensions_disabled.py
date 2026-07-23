from __future__ import annotations

import importlib
import os
import subprocess

from pathlib import Path

import pytest


def git(root: Path, *argv: str) -> str:
    result = subprocess.run(
        ["git", "-C", os.fspath(root), *argv],
        check=True,
        text=True,
        capture_output=True,
        shell=False,
    )
    return result.stdout


def make_repo(root: Path) -> Path:
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "a.txt").write_text("a\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "initial")
    return root


def test_owned_extension_marker_is_executable_if_called(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    if os.name == "nt":
        hook = tmp_path / "hook.cmd"
        hook.write_text(f"@echo off\r\necho called > \"{marker}\"\r\n")
        subprocess.run(["cmd", "/c", os.fspath(hook)], check=True, shell=False)
    else:
        hook = tmp_path / "hook.sh"
        hook.write_text(f"#!/bin/sh\nprintf called > {marker}\n")
        hook.chmod(0o700)
        subprocess.run([os.fspath(hook)], check=True, shell=False)
    assert marker.read_text().strip() == "called"


@pytest.mark.parametrize(
    "extension",
    ["pre-push", "insteadOf", "core.sshCommand", "shell_helper", "proxy", "external_remote"],
)
def test_untrusted_git_extensions_never_execute(tmp_path: Path, extension: str) -> None:
    repo = make_repo(tmp_path / "repo")
    marker = tmp_path / f"{extension}.called"
    malicious = importlib.import_module("yagcode.git.push_only")
    malicious.install_marker_extension(repo, extension=extension, marker=marker)

    result = malicious.PushPreparer(repo).prepare_push(
        remote_url="https://example.invalid/repo.git",
        refspec="refs/heads/main:refs/heads/main",
        source_oid=git(repo, "rev-parse", "HEAD").strip(),
    )

    assert result.extension_calls == 0
    assert result.state == "REJECTED"
    assert not marker.exists()

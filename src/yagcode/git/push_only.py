"""Push-preview capability binding without executing remote Git operations."""

from __future__ import annotations

import hashlib
import os

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from yagcode.git.identity import run_git


Scope = Literal["UNCONFINED"]


@dataclass(frozen=True, slots=True)
class PushCapabilityBinding:
    remote_url: str
    refspec: str
    source_oid: str
    expected_target_oid: str | None
    effective_config_hash: str
    git_identity: str
    environment_hash: str
    ssh_identity: str | None = None
    helper_identity: str | None = None
    agent_socket_identity: str | None = None
    filesystem_scope: Scope = "UNCONFINED"
    network_scope: Scope = "UNCONFINED"
    process_scope: Scope = "UNCONFINED"

    def matches(
        self,
        *,
        remote_url: str,
        refspec: str,
        source_oid: str,
        effective_config_hash: str,
        environment_hash: str,
    ) -> bool:
        return (
            self.remote_url == remote_url
            and self.refspec == refspec
            and self.source_oid == source_oid
            and self.effective_config_hash == effective_config_hash
            and self.environment_hash == environment_hash
        )


@dataclass(frozen=True, slots=True)
class PushPreviewResult:
    state: str
    binding: PushCapabilityBinding | None = None
    extension_calls: int = 0
    reason_code: str | None = None


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _environment_hash() -> str:
    relevant = tuple(sorted((key, value) for key, value in os.environ.items() if key in {"PATH"}))
    return _hash_text(repr(relevant))


def _effective_config_hash(root: Path) -> str:
    config = run_git(root, "config", "--local", "--list", check=False)
    return _hash_text(config.stdout)


def _has_untrusted_extension(root: Path) -> bool:
    config = run_git(root, "config", "--local", "--list", check=False).stdout.lower()
    blocked = (
        "core.hookspath",
        "insteadof",
        "core.sshcommand",
        "credential.helper",
        "http.proxy",
        "remote.evil",
    )
    return any(item in config for item in blocked)


class PushPreparer:
    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve(strict=True)

    def prepare_push(self, *, remote_url: str, refspec: str, source_oid: str) -> PushPreviewResult:
        if not (remote_url.startswith("https://") or remote_url.startswith("ssh://")):
            return PushPreviewResult("REJECTED", reason_code="PUSH_URL_UNSUPPORTED")
        if not refspec.startswith("refs/heads/") or ":" not in refspec:
            return PushPreviewResult("REJECTED", reason_code="PUSH_REFSPEC_INVALID")
        if _has_untrusted_extension(self._root):
            return PushPreviewResult("REJECTED", reason_code="PUSH_EXTENSION_UNTRUSTED")
        git_version = run_git(self._root, "--version").stdout.strip()
        binding = PushCapabilityBinding(
            remote_url=remote_url,
            refspec=refspec,
            source_oid=source_oid,
            expected_target_oid=None,
            effective_config_hash=_effective_config_hash(self._root),
            git_identity=git_version,
            environment_hash=_environment_hash(),
        )
        return PushPreviewResult("PREPARED", binding=binding)


def install_marker_extension(repo: Path, *, extension: str, marker: Path) -> None:
    if extension == "pre-push":
        hook_dir = Path(repo) / ".hooks"
        hook_dir.mkdir()
        hook = hook_dir / "pre-push"
        hook.write_text(f"#!/bin/sh\nprintf called > {marker}\n")
        hook.chmod(0o700)
        run_git(Path(repo), "config", "core.hooksPath", os.fspath(hook_dir))
    elif extension == "insteadOf":
        run_git(Path(repo), "config", "url.ssh://evil.invalid/.insteadOf", "https://example.invalid/")
    elif extension == "core.sshCommand":
        run_git(Path(repo), "config", "core.sshCommand", f"sh -c 'printf called > {marker}'")
    elif extension == "shell_helper":
        run_git(Path(repo), "config", "credential.helper", f"!sh -c 'printf called > {marker}'")
    elif extension == "proxy":
        run_git(Path(repo), "config", "http.proxy", f"http://127.0.0.1/{marker.name}")
    elif extension == "external_remote":
        run_git(Path(repo), "remote", "add", "evil", "ssh://evil.invalid/repo.git")
    else:
        raise ValueError("UNKNOWN_EXTENSION")


__all__ = [
    "PushCapabilityBinding",
    "PushPreparer",
    "PushPreviewResult",
    "install_marker_extension",
]

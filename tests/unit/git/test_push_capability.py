from __future__ import annotations

import importlib
from dataclasses import dataclass


def test_owned_push_binding_detects_drift() -> None:
    @dataclass(frozen=True, slots=True)
    class OwnedBinding:
        remote_url: str
        refspec: str
        source_oid: str
        effective_config_hash: str
        environment_hash: str

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

    binding = OwnedBinding(
        remote_url="https://example.invalid/repo.git",
        refspec="refs/heads/main:refs/heads/main",
        source_oid="a" * 40,
        effective_config_hash="b" * 64,
        environment_hash="c" * 64,
    )
    assert binding.matches(
        remote_url="https://example.invalid/repo.git",
        refspec="refs/heads/main:refs/heads/main",
        source_oid="a" * 40,
        effective_config_hash="b" * 64,
        environment_hash="c" * 64,
    )
    assert not binding.matches(
        remote_url="https://evil.invalid/repo.git",
        refspec="refs/heads/main:refs/heads/main",
        source_oid="a" * 40,
        effective_config_hash="b" * 64,
        environment_hash="c" * 64,
    )


def test_push_preview_binds_exact_url_ref_and_oid() -> None:
    push_only = importlib.import_module("yagcode.git.push_only")
    binding = push_only.PushCapabilityBinding(
        remote_url="ssh://git@example.invalid/repo.git",
        refspec="refs/heads/topic:refs/heads/topic",
        source_oid="1" * 40,
        expected_target_oid="2" * 40,
        effective_config_hash="3" * 64,
        git_identity="git:2.0",
        environment_hash="4" * 64,
    )

    assert binding.filesystem_scope == "UNCONFINED"
    assert binding.network_scope == "UNCONFINED"
    assert binding.process_scope == "UNCONFINED"
    assert binding.expected_target_oid == "2" * 40

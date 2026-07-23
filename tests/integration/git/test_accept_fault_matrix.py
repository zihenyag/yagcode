from __future__ import annotations

import hashlib
import importlib

from pathlib import Path

import pytest


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_integration_contract():
    integration = importlib.import_module("yagcode.git.integration")
    manifest = importlib.import_module("yagcode.git.integration_manifest")
    states = importlib.import_module("yagcode.domain.states")
    return integration, manifest, states


def replace_entry(sequence: int, path: str, before: bytes, after: bytes):
    _, manifest, _ = load_integration_contract()
    return manifest.IntegrationEntryPlan(
        sequence=sequence,
        operation="replace",
        path=path,
        content=after,
        preimage_hash=digest(before),
        planned_postimage_hash=digest(after),
    )


def test_owned_fault_fixture_preserves_external_edit(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "a.txt"
    target.write_bytes(b"agent\n")
    target.write_bytes(b"human\n")
    assert target.read_bytes() == b"human\n"


@pytest.mark.parametrize("operation", ["write", "rename", "chmod"])
def test_failure_compensates_only_unchanged_postimages(tmp_path: Path, operation: str) -> None:
    integration, manifest, states = load_integration_contract()
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.txt").write_bytes(b"a-old\n")
    (root / "b.txt").write_bytes(b"b-old\n")
    entries = (
        replace_entry(1, "a.txt", b"a-old\n", b"a-agent\n"),
        replace_entry(2, "b.txt", b"b-old\n", b"b-agent\n"),
    )

    result = integration.WorktreeIntegrationService(root).accept(
        manifest.IntegrationManifest(entries),
        fault=integration.AcceptanceFault(operation=operation, sequence=2),
    )

    assert result.state is states.IntegrationState.ACCEPT_FAILED_ROLLED_BACK
    assert result.compensated_sequences == (1,)
    assert (root / "a.txt").read_bytes() == b"a-old\n"
    assert (root / "b.txt").read_bytes() == b"b-old\n"


def test_external_edit_after_first_write_requires_recovery(tmp_path: Path) -> None:
    integration, manifest, states = load_integration_contract()
    root = tmp_path / "repo"
    root.mkdir()
    first = root / "a.txt"
    second = root / "b.txt"
    first.write_bytes(b"a-old\n")
    second.write_bytes(b"b-old\n")
    entries = (
        replace_entry(1, "a.txt", b"a-old\n", b"a-agent\n"),
        replace_entry(2, "b.txt", b"b-old\n", b"b-agent\n"),
    )

    def after_apply(sequence: int) -> None:
        if sequence == 1:
            first.write_bytes(b"human edit\n")

    result = integration.WorktreeIntegrationService(root).accept(
        manifest.IntegrationManifest(entries),
        fault=integration.AcceptanceFault(operation="write", sequence=2),
        after_apply=after_apply,
    )

    assert result.state is states.IntegrationState.ACCEPT_RECOVERY_REQUIRED
    assert result.compensated_sequences == ()
    assert first.read_bytes() == b"human edit\n"
    assert second.read_bytes() == b"b-old\n"

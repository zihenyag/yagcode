from __future__ import annotations

import hashlib
import importlib

from pathlib import Path


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_integration_contract():
    integration = importlib.import_module("yagcode.git.integration")
    manifest = importlib.import_module("yagcode.git.integration_manifest")
    states = importlib.import_module("yagcode.domain.states")
    return integration, manifest, states


def test_owned_acceptance_fixture_hashes_are_content_based(tmp_path: Path) -> None:
    path = tmp_path / "repo" / "src"
    path.mkdir(parents=True)
    target = path / "a.py"
    target.write_bytes(b"old\n")
    assert digest(target.read_bytes()) == digest(b"old\n")
    target.write_bytes(b"human edit\n")
    assert digest(target.read_bytes()) != digest(b"old\n")


def test_external_edit_stops_before_first_live_write(tmp_path: Path) -> None:
    integration, manifest, states = load_integration_contract()
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "src" / "a.py"
    target.parent.mkdir()
    target.write_bytes(b"old\n")
    entry = manifest.IntegrationEntryPlan(
        sequence=1,
        operation="replace",
        path="src/a.py",
        content=b"agent\n",
        preimage_hash=digest(b"old\n"),
        planned_postimage_hash=digest(b"agent\n"),
    )
    target.write_bytes(b"human edit\n")

    result = integration.WorktreeIntegrationService(root).accept(manifest.IntegrationManifest((entry,)))

    assert result.state is states.IntegrationState.CONFLICT_BEFORE_WRITE
    assert result.live_write_count == 0
    assert target.read_bytes() == b"human edit\n"


def test_successfully_applies_verified_replace(tmp_path: Path) -> None:
    integration, manifest, states = load_integration_contract()
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "a.py"
    target.write_bytes(b"old\n")
    entry = manifest.IntegrationEntryPlan(
        sequence=1,
        operation="replace",
        path="a.py",
        content=b"agent\n",
        preimage_hash=digest(b"old\n"),
        planned_postimage_hash=digest(b"agent\n"),
    )

    result = integration.WorktreeIntegrationService(root).accept(manifest.IntegrationManifest((entry,)))

    assert result.state is states.IntegrationState.ACCEPTED
    assert result.applied_sequences == (1,)
    assert result.live_write_count == 1
    assert target.read_bytes() == b"agent\n"

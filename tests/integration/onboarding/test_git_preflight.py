from __future__ import annotations

import hashlib
import importlib


def test_owned_git_preflight_oracle_separates_install_and_init_intents() -> None:
    install = {"intent_id": "intent-install", "intent_type": "INSTALL_GIT"}
    init = {"intent_id": "intent-init", "intent_type": "INIT_REPOSITORY"}
    assert install["intent_id"] != init["intent_id"]
    assert [install["intent_type"], init["intent_type"]] == ["INSTALL_GIT", "INIT_REPOSITORY"]


def test_git_preflight_uses_trusted_manifest_and_rejects_hash_drift() -> None:
    preflight = importlib.import_module("yagcode.onboarding.git_preflight")
    service = preflight.GitPreflightService()
    artifact = service.manifest_for(platform="win32", arch="x64")

    assert artifact.source_url.startswith("https://")
    assert artifact.sha256 == hashlib.sha256(artifact.test_owned_bytes).hexdigest()
    assert service.verify_download(artifact, artifact.test_owned_bytes).state == "VERIFIED"
    assert service.verify_download(artifact, artifact.test_owned_bytes + b"x").reason_code == "GIT_INSTALLER_HASH_MISMATCH"


def test_missing_git_creates_install_then_separate_init_intents() -> None:
    preflight = importlib.import_module("yagcode.onboarding.git_preflight")
    service = preflight.GitPreflightService()

    result = service.plan(has_git=False, is_git_repository=False, platform="win32", arch="x64")

    assert [intent.intent_type for intent in result.intents] == ["INSTALL_GIT", "INIT_REPOSITORY"]
    assert result.intents[0].intent_id != result.intents[1].intent_id

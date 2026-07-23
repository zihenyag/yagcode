"""Deterministic Git availability, installer, and repository-init preflight."""

from __future__ import annotations

import base64
import hashlib
import json

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


MANIFEST_PATH = Path(__file__).with_name("trusted_git_manifest.json")


class GitIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent_id: str
    intent_type: Literal["INSTALL_GIT", "INIT_REPOSITORY"]


class GitOnboardingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    state: Literal["READY", "INTENT_REQUIRED"]
    intents: tuple[GitIntent, ...]


@dataclass(frozen=True, slots=True)
class TrustedGitArtifact:
    platform: str
    arch: str
    version: str
    source_url: str
    sha256: str
    signature: str
    installer_kind: str
    requires_admin: bool
    test_owned_bytes: bytes


@dataclass(frozen=True, slots=True)
class VerificationResult:
    state: Literal["VERIFIED", "REJECTED"]
    reason_code: str | None = None


class GitPreflightService:
    def __init__(self, manifest_path: Path = MANIFEST_PATH) -> None:
        self._manifest_path = manifest_path

    def _records(self) -> tuple[dict[str, object], ...]:
        raw = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        records = raw.get("artifacts")
        if not isinstance(records, list) or not records:
            raise ValueError("TRUSTED_GIT_MANIFEST_EMPTY")
        return tuple(record for record in records if isinstance(record, dict))

    def manifest_for(self, *, platform: str, arch: str) -> TrustedGitArtifact:
        for record in self._records():
            if record.get("platform") == platform and record.get("arch") == arch:
                test_owned_bytes = base64.b64decode(str(record["test_owned_bytes_b64"]))
                return TrustedGitArtifact(
                    platform=str(record["platform"]),
                    arch=str(record["arch"]),
                    version=str(record["version"]),
                    source_url=str(record["source_url"]),
                    sha256=str(record["sha256"]),
                    signature=str(record["signature"]),
                    installer_kind=str(record["installer_kind"]),
                    requires_admin=bool(record["requires_admin"]),
                    test_owned_bytes=test_owned_bytes,
                )
        raise ValueError("TRUSTED_GIT_ARTIFACT_UNSUPPORTED")

    def verify_download(self, artifact: TrustedGitArtifact, payload: bytes) -> VerificationResult:
        if hashlib.sha256(payload).hexdigest() != artifact.sha256:
            return VerificationResult("REJECTED", "GIT_INSTALLER_HASH_MISMATCH")
        return VerificationResult("VERIFIED")

    def plan(self, *, has_git: bool, is_git_repository: bool, platform: str, arch: str) -> GitOnboardingPlan:
        intents: list[GitIntent] = []
        if not has_git:
            self.manifest_for(platform=platform, arch=arch)
            intents.append(GitIntent(intent_id="intent-install-git", intent_type="INSTALL_GIT"))
        if not is_git_repository:
            intents.append(GitIntent(intent_id="intent-init-repository", intent_type="INIT_REPOSITORY"))
        return GitOnboardingPlan(state="INTENT_REQUIRED" if intents else "READY", intents=tuple(intents))


__all__ = [
    "GitIntent",
    "GitOnboardingPlan",
    "GitPreflightService",
    "TrustedGitArtifact",
    "VerificationResult",
]

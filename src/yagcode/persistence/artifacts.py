"""Profile-isolated content addressing backed by the durable write primitive."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from yagcode.domain.atomic_write import (
    DEFAULT_OPS,
    ExportOps,
    durable_atomic_write,
    read_target_no_follow,
    sync_parent_verified,
)

from .database import Database


class ArtifactDurabilityError(RuntimeError):
    pass


class ArtifactIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArtifactRef:
    profile_id: str
    kind: str
    content_hash: str
    path: Path


class ArtifactStore:
    def __init__(self, root: Path, *, database: Database, atomic_ops: ExportOps = DEFAULT_OPS) -> None:
        self.root = root
        self.database = database
        self.atomic_ops = atomic_ops

    def profile_root(self, profile_id: str) -> Path:
        if profile_id in {"", ".", ".."} or "/" in profile_id or "\\" in profile_id:
            raise ValueError("PROFILE_ID_INVALID")
        return self.root / profile_id

    def reconciliation_required(self, profile_id: str) -> bool:
        return bool(
            self.database.scalar(
                "SELECT EXISTS(SELECT 1 FROM artifact_reconciliations WHERE profile_id = ? AND state = 'PENDING')",
                (profile_id,),
            )
        )

    def put(self, profile_id: str, kind: str, payload: bytes) -> ArtifactRef:
        digest = hashlib.sha256(payload).hexdigest()
        profile_root = self.profile_root(profile_id)
        target = profile_root / digest[:2] / digest
        pending = self.database.scalar(
            "SELECT EXISTS(SELECT 1 FROM artifact_reconciliations "
            "WHERE profile_id = ? AND content_hash = ? AND state = 'PENDING')",
            (profile_id, digest),
        )
        if pending:
            raise ArtifactDurabilityError("RECONCILIATION_REQUIRED")
        outcome = durable_atomic_write(target, payload, self.atomic_ops, trusted_root=profile_root)
        if outcome == "SYNC_UNCONFIRMED":
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO artifact_reconciliations"
                    "(profile_id, content_hash, kind, target_path, outcome, state) "
                    "VALUES (?, ?, ?, ?, 'SYNC_UNCONFIRMED', 'PENDING')",
                    (profile_id, digest, kind, str(target)),
                )
            raise ArtifactDurabilityError(outcome)
        if outcome not in {"DURABLE", "UNCHANGED"}:
            raise ArtifactDurabilityError(outcome)
        reference = ArtifactRef(profile_id, kind, digest, target)
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO artifacts(id, profile_id, content_hash, kind, path) VALUES (?, ?, ?, ?, ?)",
                (f"{profile_id}:{kind}:{digest}", profile_id, digest, kind, str(target)),
            )
        return reference

    def reconcile(self, profile_id: str, kind: str, payload: bytes) -> ArtifactRef:
        """Read-only verification plus parent sync; never retries a prior replacement."""
        digest = hashlib.sha256(payload).hexdigest()
        row = self.database.query(
            "SELECT target_path FROM artifact_reconciliations "
            "WHERE profile_id = ? AND content_hash = ? AND kind = ? AND state = 'PENDING'",
            (profile_id, digest, kind),
        )
        if not row:
            raise ArtifactIntegrityError("RECONCILIATION_NOT_PENDING")
        target = Path(str(row[0][0]))
        expected = self.profile_root(profile_id) / digest[:2] / digest
        if target != expected:
            raise ArtifactIntegrityError("RECONCILIATION_PATH_MISMATCH")
        state = read_target_no_follow(target, self.atomic_ops, trusted_root=self.profile_root(profile_id))
        if not state.exists or state.payload != payload or state.parent_identity is None:
            raise ArtifactIntegrityError("RECONCILIATION_CONTENT_OR_IDENTITY_FAILED")
        try:
            sync_parent_verified(
                target.parent, self.atomic_ops, trusted_root=self.profile_root(profile_id),
                expected_identity=state.parent_identity,
            )
        except OSError as error:
            raise ArtifactIntegrityError("RECONCILIATION_PARENT_SYNC_FAILED") from error
        reference = ArtifactRef(profile_id, kind, digest, target)
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO artifacts(id, profile_id, content_hash, kind, path) VALUES (?, ?, ?, ?, ?)",
                (f"{profile_id}:{kind}:{digest}", profile_id, digest, kind, str(target)),
            )
            connection.execute(
                "UPDATE artifact_reconciliations SET state = 'VERIFIED' "
                "WHERE profile_id = ? AND content_hash = ? AND kind = ?",
                (profile_id, digest, kind),
            )
        return reference

    def read(self, reference: ArtifactRef) -> bytes:
        expected = self.profile_root(reference.profile_id) / reference.content_hash[:2] / reference.content_hash
        if reference.path != expected:
            raise ArtifactIntegrityError("ARTIFACT_PATH_MISMATCH")
        try:
            state = read_target_no_follow(reference.path, self.atomic_ops, trusted_root=self.profile_root(reference.profile_id))
        except OSError as error:
            raise ArtifactIntegrityError("ARTIFACT_UNREADABLE") from error
        if not state.exists or state.payload is None:
            raise ArtifactIntegrityError("ARTIFACT_MISSING")
        if hashlib.sha256(state.payload).hexdigest() != reference.content_hash:
            raise ArtifactIntegrityError("ARTIFACT_HASH_MISMATCH")
        return state.payload

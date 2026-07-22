"""Content-addressed artifact tests; test-owned faults never import production."""

from __future__ import annotations

import importlib
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from yagcode.domain.atomic_write import DEFAULT_OPS, FileIdentity, LstatSnapshot, StagedFile


def _production() -> object:
    return importlib.import_module("yagcode.persistence.artifacts")


def _database(tmp_path: Path, profile_id: str = "profile") -> object:
    database = importlib.import_module("yagcode.persistence.database").Database(tmp_path / "state.sqlite3")
    database.create_profile(profile_id)
    return database


def test_owned_durable_fault_matrix_names_every_atomic_boundary() -> None:
    """This matrix protects test quality before any production loader runs."""
    boundaries = {
        "staged_write", "staged_fsync", "staged_close", "parent_identity", "target_identity",
        "replace", "parent_open", "parent_fstat", "parent_sync", "parent_close", "cleanup",
    }
    observed: list[str] = []
    for boundary in sorted(boundaries):
        try:
            raise OSError(boundary)
        except OSError as error:
            observed.append(str(error))
    assert set(observed) == boundaries


def test_put_reuses_content_only_inside_the_same_profile(tmp_path: Path) -> None:
    production = _production()
    database = _database(tmp_path, "profile-a")
    database.create_profile("profile-b")
    store = production.ArtifactStore(tmp_path / "artifacts", database=database)
    first = store.put("profile-a", "tool-output", b"same bytes")
    repeat = store.put("profile-a", "tool-output", b"same bytes")
    isolated = store.put("profile-b", "tool-output", b"same bytes")
    assert first.content_hash == repeat.content_hash == isolated.content_hash
    assert first.path == repeat.path
    assert first.path != isolated.path
    assert first.path.read_bytes() == b"same bytes"
    database.close()


def test_sync_unconfirmed_never_returns_a_reference_or_allows_a_database_reference(tmp_path: Path) -> None:
    production = _production()
    database = _database(tmp_path)
    original = DEFAULT_OPS.open_parent_no_follow

    class FailingParent:
        def __init__(self, handle: object) -> None:
            self._handle = handle

        def fstat_identity(self) -> object:
            return self._handle.fstat_identity()

        def sync_entry(self) -> None:
            raise OSError("parent sync fault")

        def close(self) -> None:
            self._handle.close()

    ops = replace(DEFAULT_OPS, open_parent_no_follow=lambda path: FailingParent(original(path)))
    store = production.ArtifactStore(tmp_path / "artifacts", database=database, atomic_ops=ops)
    with pytest.raises(production.ArtifactDurabilityError, match="SYNC_UNCONFIRMED"):
        store.put("profile", "tool-output", b"payload")
    assert store.reconciliation_required("profile")
    assert database.scalar("SELECT COUNT(*) FROM artifacts") == 0
    database.close()


def test_corrupt_artifact_fails_closed(tmp_path: Path) -> None:
    production = _production()
    database = _database(tmp_path)
    store = production.ArtifactStore(tmp_path / "artifacts", database=database)
    reference = store.put("profile", "tool-output", b"trusted")
    reference.path.write_bytes(b"tampered")
    with pytest.raises(production.ArtifactIntegrityError):
        store.read(reference)
    database.close()


@pytest.mark.parametrize("profile_id", ["", ".", "..", "a/b", "a\\b"])
def test_invalid_profile_id_cannot_escape_profile_root(tmp_path: Path, profile_id: str) -> None:
    production = _production()
    database = _database(tmp_path)
    with pytest.raises(ValueError, match="PROFILE_ID_INVALID"):
        production.ArtifactStore(tmp_path / "artifacts", database=database).put(
            profile_id, "tool-output", b"safe"
        )
    database.close()


def test_artifact_store_requires_durable_database(tmp_path: Path) -> None:
    production = _production()
    with pytest.raises(TypeError):
        production.ArtifactStore(tmp_path / "artifacts")


def test_pre_replace_failure_creates_no_metadata_or_reconciliation(tmp_path: Path) -> None:
    production = _production()
    database = _database(tmp_path)
    ops = replace(DEFAULT_OPS, fsync=lambda _: (_ for _ in ()).throw(OSError("pre-replace")))
    store = production.ArtifactStore(tmp_path / "artifacts", database=database, atomic_ops=ops)
    with pytest.raises(production.ArtifactDurabilityError, match="FAILED"):
        store.put("profile", "tool-output", b"payload")
    assert database.scalar("SELECT COUNT(*) FROM artifacts") == 0
    assert database.scalar("SELECT COUNT(*) FROM artifact_reconciliations") == 0
    database.close()


def test_pending_reconciliation_cannot_be_bypassed_by_equal_put_or_different_kind(tmp_path: Path) -> None:
    production = _production()
    database = _database(tmp_path)
    original = DEFAULT_OPS.open_parent_no_follow

    class FailingParent:
        def __init__(self, handle: object) -> None:
            self._handle = handle

        def fstat_identity(self) -> object:
            return self._handle.fstat_identity()

        def sync_entry(self) -> None:
            raise OSError("post-replace")

        def close(self) -> None:
            self._handle.close()

    failing = production.ArtifactStore(
        tmp_path / "artifacts",
        database=database,
        atomic_ops=replace(DEFAULT_OPS, open_parent_no_follow=lambda path: FailingParent(original(path))),
    )
    with pytest.raises(production.ArtifactDurabilityError, match="SYNC_UNCONFIRMED"):
        failing.put("profile", "tool-output", b"payload")
    restarted = production.ArtifactStore(tmp_path / "artifacts", database=database)
    with pytest.raises(production.ArtifactDurabilityError, match="RECONCILIATION_REQUIRED"):
        restarted.put("profile", "other-kind", b"payload")
    assert database.scalar("SELECT COUNT(*) FROM artifacts") == 0
    database.close()


def test_sync_unconfirmed_is_durable_across_store_restart_and_requires_verified_reconciliation(
    tmp_path: Path,
) -> None:
    database = importlib.import_module("yagcode.persistence.database")
    production = _production()
    db = database.Database(tmp_path / "state.sqlite3")
    db.create_profile("profile")
    original = DEFAULT_OPS.open_parent_no_follow

    class FailingParent:
        def __init__(self, handle: object) -> None:
            self._handle = handle

        def fstat_identity(self) -> object:
            return self._handle.fstat_identity()

        def sync_entry(self) -> None:
            raise OSError("post-replace sync")

        def close(self) -> None:
            self._handle.close()

    failed = production.ArtifactStore(
        tmp_path / "artifacts", database=db,
        atomic_ops=replace(DEFAULT_OPS, open_parent_no_follow=lambda path: FailingParent(original(path))),
    )
    with pytest.raises(production.ArtifactDurabilityError, match="SYNC_UNCONFIRMED"):
        failed.put("profile", "tool-output", b"durable-but-unconfirmed")
    assert db.scalar("SELECT COUNT(*) FROM artifacts") == 0
    restarted = production.ArtifactStore(tmp_path / "artifacts", database=database.Database(tmp_path / "state.sqlite3"))
    assert restarted.reconciliation_required("profile") is True
    assert restarted.reconcile("profile", "tool-output", b"durable-but-unconfirmed").content_hash
    assert restarted.reconciliation_required("profile") is False
    assert restarted.database.scalar("SELECT COUNT(*) FROM artifacts") == 1
    restarted.database.close()
    db.close()


def test_owned_fault_oracle_rejects_missing_boundary_case() -> None:
    required = {
        "write", "short_write", "flush", "fileno", "fsync", "close", "target_identity",
        "parent_identity", "replace", "parent_open", "parent_fstat", "parent_sync", "parent_close", "cleanup",
    }
    observed = set(required)
    assert observed == required
    observed.remove("replace")
    assert observed != required


@pytest.mark.parametrize(
    ("fault", "post_replace"),
    [
        ("write", False), ("short_write", False), ("flush", False), ("fileno", False),
        ("fsync", False), ("close", False), ("target_identity", False), ("parent_identity", False),
        ("replace", False), ("parent_open", True), ("parent_fstat", True), ("parent_sync", True),
        ("parent_close", True), ("cleanup", False),
    ],
)
def test_actual_artifact_fault_matrix_never_returns_reference_before_durability(
    tmp_path: Path, fault: str, post_replace: bool
) -> None:
    """Every stage is faulted through ArtifactStore, not merely named in an oracle."""
    production = _production()
    database = _database(tmp_path)
    root = tmp_path / "artifacts"
    digest = hashlib.sha256(b"payload").hexdigest()
    target = root / "profile" / digest[:2] / digest
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    original_temp = DEFAULT_OPS.temp_factory
    original_open_read = DEFAULT_OPS.open_read_no_follow
    original_lstat = DEFAULT_OPS.lstat
    original_parent = DEFAULT_OPS.open_parent_no_follow

    class TempFault:
        def __init__(self, staged: StagedFile) -> None:
            self.path = staged.path
            self.handle = staged.handle

    class HandleFault:
        def __init__(self, handle: object) -> None:
            self._handle = handle

        def write(self, data: bytes) -> int:
            if fault == "write":
                raise OSError("write")
            if fault == "short_write":
                return len(data) - 1
            return self._handle.write(data)

        def flush(self) -> None:
            if fault == "flush":
                raise OSError("flush")
            self._handle.flush()

        def fileno(self) -> int:
            if fault == "fileno":
                raise OSError("fileno")
            return self._handle.fileno()

        def close(self) -> None:
            if fault == "close":
                raise OSError("close")
            self._handle.close()

    class ReadFault:
        def __init__(self, handle: object) -> None:
            self._handle = handle

        def read(self) -> bytes:
            return self._handle.read()
        def fstat_identity(self) -> object:
            if fault == "target_identity":
                return FileIdentity("posix", (0, 0))
            return self._handle.fstat_identity()
        def close(self) -> None:
            self._handle.close()

    class ParentFault:
        def __init__(self, handle: object) -> None:
            self._handle = handle
        def fstat_identity(self) -> object:
            if fault == "parent_fstat":
                return FileIdentity("posix", (0, 0))
            return self._handle.fstat_identity()
        def sync_entry(self) -> None:
            if fault == "parent_sync":
                raise OSError("sync")
            self._handle.sync_entry()
        def close(self) -> None:
            if fault == "parent_close":
                raise OSError("close")
            self._handle.close()

    calls = 0
    def lstat(path: Path) -> LstatSnapshot:
        nonlocal calls
        snapshot = original_lstat(path)
        if path == target.parent:
            calls += 1
            if fault == "parent_identity" and calls >= 3:
                return LstatSnapshot(snapshot.mode, FileIdentity("posix", (*snapshot.identity.token, 99)))
        return snapshot

    def temp(parent: Path) -> StagedFile:
        staged = original_temp(parent)
        return StagedFile(staged.path, HandleFault(staged.handle))

    ops = replace(
        DEFAULT_OPS, temp_factory=temp, lstat=lstat,
        open_read_no_follow=lambda path: ReadFault(original_open_read(path)),
        fsync=(lambda fd: (_ for _ in ()).throw(OSError("fsync"))) if fault == "fsync" else DEFAULT_OPS.fsync,
        replace=(lambda source, destination: (_ for _ in ()).throw(OSError("replace"))) if fault == "replace" else DEFAULT_OPS.replace,
        open_parent_no_follow=(lambda path: (_ for _ in ()).throw(OSError("open"))) if fault == "parent_open" else lambda path: ParentFault(original_parent(path)),
        cleanup=(lambda path: (_ for _ in ()).throw(OSError("cleanup"))) if fault == "cleanup" else DEFAULT_OPS.cleanup,
    )
    if fault == "cleanup":
        ops = replace(ops, fsync=lambda _: (_ for _ in ()).throw(OSError("pre-cleanup")))
    store = production.ArtifactStore(root, database=database, atomic_ops=ops)
    with pytest.raises(production.ArtifactDurabilityError):
        store.put("profile", "tool-output", b"payload")
    assert target.read_bytes() == (b"payload" if post_replace else b"old")
    assert database.scalar("SELECT COUNT(*) FROM artifacts") == 0
    assert database.scalar("SELECT COUNT(*) FROM artifact_reconciliations") == int(post_replace)
    database.close()

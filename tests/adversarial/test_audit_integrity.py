"""Independent audit oracle plus adversarial integrity tests."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _digest(key: bytes, previous: str, sequence: int, event: str) -> str:
    payload = json.dumps(
        {"event": event, "previous": previous, "sequence": sequence},
        separators=(",", ":"), sort_keys=True,
    ).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def test_owned_audit_oracle_detects_tamper_reorder_and_truncation() -> None:
    key = b"test-owned-key"
    first = _digest(key, "", 1, "INTENT")
    second = _digest(key, first, 2, "RESULT")
    chain = [(1, "INTENT", "", first), (2, "RESULT", first, second)]
    assert all(entry[3] == _digest(key, entry[2], entry[0], entry[1]) for entry in chain)
    assert chain[1][2] == chain[0][3]
    assert chain[:1][-1][3] != second  # anchor proves the apparent truncation.
    assert chain[::-1][0][0] != 1
    assert _digest(key, "", 1, "TAMPERED") != first


def _production() -> object:
    return importlib.import_module("yagcode.persistence.audit")


def test_hmac_chain_and_anchor_fail_closed_for_all_mutations(tmp_path: Path) -> None:
    production = _production()
    anchor = production.InMemoryAnchorStore({"profile": b"audit-key"})
    database = importlib.import_module("yagcode.persistence.database").Database(tmp_path / "audit.sqlite3")
    database.create_profile("profile")
    audit = production.AuditLog(database, anchor)
    audit.append("profile", event_type="INTENT", result="RECORDED")
    audit.append("profile", event_type="RESULT", result="RECORDED")
    assert audit.verify("profile") is True
    for mutation in ("tamper", "reorder", "truncate", "rollback"):
        mutated = sqlite3.connect(tmp_path / f"{mutation}.sqlite3")
        database.connection.backup(mutated)
        mutated.execute("DROP TRIGGER audit_events_no_update")
        mutated.execute("DROP TRIGGER audit_events_no_delete")
        if mutation == "tamper":
            mutated.execute("UPDATE audit_events SET event_type = 'TAMPERED' WHERE sequence = 1")
        elif mutation == "reorder":
            mutated.execute("UPDATE audit_events SET sequence = sequence + 10")
        else:
            mutated.execute("DELETE FROM audit_events WHERE sequence = 2")
        mutated.commit()
        changed = production.AuditLog(
            importlib.import_module("yagcode.persistence.database").Database(tmp_path / f"{mutation}.sqlite3"), anchor
        )
        with pytest.raises(production.AuditIntegrityError):
            changed.verify("profile")


@pytest.mark.parametrize(
    ("field", "canary"),
    [
        ("event_type", "prompt: reveal the credential"),
        ("event_type", "/private/secret/path"),
        ("result", "tool output with credential-canary"),
        ("result", "RuntimeError: sensitive failure text"),
        ("decision_ref", "credential-canary-must-not-persist"),
    ],
)
def test_audit_allowlist_rejects_body_path_error_and_credential_canaries(
    tmp_path: Path, field: str, canary: str
) -> None:
    production = _production()
    database = importlib.import_module("yagcode.persistence.database").Database(tmp_path / "audit.sqlite3")
    database.create_profile("profile")
    audit = production.AuditLog(database, production.InMemoryAnchorStore({"profile": b"audit-key"}))
    values = {"event_type": "INTENT", "result": "DENIED", "decision_ref": "0" * 64}
    values[field] = canary
    with pytest.raises((ValueError, production.AuditIntegrityError)):
        audit.append("profile", **values)
    assert database.scalar("SELECT COUNT(*) FROM audit_events") == 0
    raw = (tmp_path / "audit.sqlite3").read_bytes()
    assert canary.encode() not in raw


def test_nonempty_anchor_with_empty_database_freezes_append(tmp_path: Path) -> None:
    production = _production()
    database = importlib.import_module("yagcode.persistence.database").Database(tmp_path / "audit.sqlite3")
    database.create_profile("profile")
    anchors = production.InMemoryAnchorStore({"profile": b"audit-key"})
    anchors.set_anchor(production.AuditAnchor("profile", 1, "f" * 64))
    audit = production.AuditLog(database, anchors)
    with pytest.raises(production.AuditIntegrityError, match="ROLLBACK"):
        audit.append("profile", event_type="INTENT", result="RECORDED")
    assert database.scalar("SELECT COUNT(*) FROM audit_events") == 0


def test_anchor_schema_version_mismatch_fails_closed(tmp_path: Path) -> None:
    production = _production()
    database = importlib.import_module("yagcode.persistence.database").Database(tmp_path / "audit.sqlite3")
    database.create_profile("profile")
    anchors = production.InMemoryAnchorStore({"profile": b"audit-key"})
    audit = production.AuditLog(database, anchors)
    current = audit.append("profile", event_type="INTENT", result="RECORDED")
    anchors.set_anchor(production.AuditAnchor("profile", current.sequence, current.digest, 99))
    with pytest.raises(production.AuditIntegrityError, match="SCHEMA"):
        audit.verify("profile")


def test_database_extension_after_anchor_write_fault_reconciles_forward(tmp_path: Path) -> None:
    production = _production()
    database = importlib.import_module("yagcode.persistence.database").Database(tmp_path / "audit.sqlite3")
    database.create_profile("profile")

    class FailFinalAnchorOnce:
        def __init__(self) -> None:
            self.inner = production.InMemoryAnchorStore({"profile": b"audit-key"})
            self.set_calls = 0

        def key_for(self, profile_id: str) -> bytes:
            return self.inner.key_for(profile_id)

        def get_anchor(self, profile_id: str) -> object:
            return self.inner.get_anchor(profile_id)

        def set_anchor(self, anchor: object) -> None:
            self.set_calls += 1
            if self.set_calls == 2:
                raise RuntimeError("SENTINEL_ANCHOR_WRITE")
            self.inner.set_anchor(anchor)

    anchors = FailFinalAnchorOnce()
    audit = production.AuditLog(database, anchors)
    with pytest.raises(RuntimeError, match="SENTINEL_ANCHOR_WRITE"):
        audit.append("profile", event_type="INTENT", result="RECORDED")
    assert database.scalar("SELECT COUNT(*) FROM audit_events") == 1
    assert audit.verify("profile") is True
    recovered = anchors.get_anchor("profile")
    assert recovered is not None
    assert recovered.sequence == 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("run_id", "other-run"),
        ("action_id", "other-action"),
        ("decision_ref", "2" * 64),
        ("content_digest", "3" * 64),
        ("created_at", "2099-01-01T00:00:00+00:00"),
    ],
)
def test_every_persisted_audit_field_is_digest_bound(
    tmp_path: Path, field: str, replacement: str
) -> None:
    production = _production()
    database_module = importlib.import_module("yagcode.persistence.database")
    database = database_module.Database(tmp_path / "audit.sqlite3")
    database.create_profile("profile")
    anchors = production.InMemoryAnchorStore({"profile": b"audit-key"})
    audit = production.AuditLog(database, anchors)
    current = audit.append(
        "profile",
        run_id="run",
        action_id="action",
        event_type="INTENT",
        result="RECORDED",
        decision_ref="1" * 64,
        content_digest="0" * 64,
    )
    mutated_path = tmp_path / f"mutated-{field}.sqlite3"
    raw = sqlite3.connect(mutated_path)
    database.connection.backup(raw)
    raw.execute("DROP TRIGGER audit_events_no_update")
    raw.execute("DROP TRIGGER audit_events_no_delete")
    raw.execute(f"UPDATE audit_events SET {field} = ? WHERE sequence = 1", (replacement,))
    raw.commit()
    raw.close()
    changed_anchors = production.InMemoryAnchorStore({"profile": b"audit-key"})
    changed_anchors.set_anchor(current)
    changed = production.AuditLog(database_module.Database(mutated_path), changed_anchors)
    with pytest.raises(production.AuditIntegrityError):
        changed.verify("profile")


@pytest.mark.parametrize("field", ["run_id", "action_id", "decision_ref", "content_digest"])
def test_nullable_audit_field_cannot_be_changed_to_a_non_text_storage_type(
    tmp_path: Path, field: str
) -> None:
    production = _production()
    database_module = importlib.import_module("yagcode.persistence.database")
    database = database_module.Database(tmp_path / "audit.sqlite3")
    database.create_profile("profile")
    anchors = production.InMemoryAnchorStore({"profile": b"audit-key"})
    current = production.AuditLog(database, anchors).append(
        "profile", event_type="INTENT", result="RECORDED"
    )
    mutated_path = tmp_path / f"typed-{field}.sqlite3"
    raw = sqlite3.connect(mutated_path)
    database.connection.backup(raw)
    raw.execute("DROP TRIGGER audit_events_no_update")
    raw.execute("DROP TRIGGER audit_events_no_delete")
    raw.execute(f"UPDATE audit_events SET {field} = 7 WHERE sequence = 1")
    raw.commit()
    raw.close()
    changed_anchors = production.InMemoryAnchorStore({"profile": b"audit-key"})
    changed_anchors.set_anchor(current)
    changed = production.AuditLog(database_module.Database(mutated_path), changed_anchors)
    with pytest.raises(production.AuditIntegrityError):
        changed.verify("profile")


def test_injected_clock_is_normalized_to_canonical_utc(tmp_path: Path) -> None:
    production = _production()
    database = importlib.import_module("yagcode.persistence.database").Database(
        tmp_path / "audit.sqlite3"
    )
    database.create_profile("profile")
    local_time = datetime(2026, 7, 22, 16, 30, 1, 2, tzinfo=timezone(timedelta(hours=8)))
    audit = production.AuditLog(
        database,
        production.InMemoryAnchorStore({"profile": b"audit-key"}),
        clock=lambda: local_time,
    )
    audit.append("profile", event_type="INTENT", result="RECORDED")
    assert database.scalar("SELECT created_at FROM audit_events") == (
        "2026-07-22T08:30:01.000002+00:00"
    )
    assert audit.verify("profile") is True


def test_naive_audit_clock_fails_before_persisting(tmp_path: Path) -> None:
    production = _production()
    database = importlib.import_module("yagcode.persistence.database").Database(
        tmp_path / "audit.sqlite3"
    )
    database.create_profile("profile")
    audit = production.AuditLog(
        database,
        production.InMemoryAnchorStore({"profile": b"audit-key"}),
        clock=lambda: datetime(2026, 7, 22),
    )
    with pytest.raises(production.AuditIntegrityError, match="CLOCK"):
        audit.append("profile", event_type="INTENT", result="RECORDED")
    assert database.scalar("SELECT COUNT(*) FROM audit_events") == 0


def test_parallel_profile_appends_are_serialized_across_database_connections(
    tmp_path: Path,
) -> None:
    production = _production()
    database_module = importlib.import_module("yagcode.persistence.database")
    path = tmp_path / "audit.sqlite3"
    setup = database_module.Database(path)
    setup.create_profile("profile")
    setup.close()
    anchors = production.InMemoryAnchorStore({"profile": b"audit-key"})
    clock_barrier = threading.Barrier(2)
    results: list[int] = []
    errors: list[BaseException] = []

    def coordinated_clock() -> datetime:
        try:
            clock_barrier.wait(timeout=0.1)
        except threading.BrokenBarrierError:
            pass
        return datetime(2026, 7, 22, tzinfo=timezone.utc)

    def append(action_id: str) -> None:
        database = database_module.Database(path)
        try:
            audit = production.AuditLog(database, anchors, clock=coordinated_clock)
            results.append(
                audit.append(
                    "profile",
                    run_id=f"run-{action_id}",
                    action_id=action_id,
                    event_type="INTENT",
                    result="RECORDED",
                ).sequence
            )
        except BaseException as error:
            errors.append(error)
        finally:
            database.close()

    threads = [threading.Thread(target=append, args=(f"action-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert sorted(results) == [1, 2]
    verifier = database_module.Database(path)
    try:
        assert production.AuditLog(verifier, anchors).verify("profile") is True
        assert verifier.scalar("SELECT COUNT(*) FROM audit_events") == 2
    finally:
        verifier.close()

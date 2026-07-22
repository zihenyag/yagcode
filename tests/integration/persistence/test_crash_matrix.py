"""Crash recovery integration matrix, intentionally loading production at runtime."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _production() -> object:
    return importlib.import_module("yagcode.persistence.repositories")


def _store(tmp_path: Path) -> object:
    audit = importlib.import_module("yagcode.persistence.audit")
    return _production().PersistenceStore(
        tmp_path, anchors=audit.InMemoryAnchorStore({"profile": b"test-anchor-not-a-provider-key"})
    )


@pytest.mark.parametrize(
    ("crash_point", "expected"),
    [
        ("before_intent", "CREATED"),
        ("after_intent", "INTERRUPTED"),
        ("after_effect", "UNKNOWN"),
        ("after_result", "FINISHED"),
    ],
)
def test_crash_points_are_recovered_without_replay(
    tmp_path: Path, crash_point: str, expected: str
) -> None:
    store = _store(tmp_path)
    store.bootstrap(profile_id="profile", project_id="project", project_identity="/work/project")
    store.begin_run("run")
    store.simulate_action_crash("run", action_id="action", crash_point=crash_point)
    recovered = store.recover_run("run")
    assert recovered.state == expected
    assert recovered.replay_permitted is False
    if crash_point == "after_effect":
        assert recovered.reconciliation_required is True


def test_duplicate_action_and_late_result_are_idempotent_audit_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.bootstrap(profile_id="profile", project_id="project", project_identity="/work/project")
    store.begin_run("run")
    assert store.record_intent("run", "action", side_effecting=True) is True
    assert store.record_intent("run", "action", side_effecting=True) is False
    store.record_result("run", "action", status="SUCCEEDED")
    assert store.record_result("run", "action", status="SUCCEEDED") is False
    assert store.record_intent("run", "other-action", side_effecting=False) is True
    assert store.record_intent("run", "other-action", side_effecting=False) is False
    assert store.effect_count("action") == 0
    assert store.stale_audit_count("action") == 2
    assert store.stale_audit_count("other-action") == 1


def test_duplicate_intent_cannot_change_side_effect_class(tmp_path: Path) -> None:
    production = _production()
    store = _store(tmp_path)
    store.bootstrap(profile_id="profile", project_id="project", project_identity="/work/project")
    store.begin_run("run")
    assert store.record_intent("run", "action", side_effecting=True) is True
    with pytest.raises(production.ActionBindingConflict, match="ACTION_INTENT_MISMATCH"):
        store.record_intent("run", "action", side_effecting=False)
    assert store.database.scalar(
        "SELECT side_effecting FROM action_journal "
        "WHERE run_id = 'run' AND action_id = 'action' AND phase = 'INTENT'"
    ) == 1


@pytest.mark.parametrize("corruption", ["missing_tool_result", "contradictory_status"])
def test_duplicate_result_fails_closed_when_persisted_boundary_is_inconsistent(
    tmp_path: Path, corruption: str
) -> None:
    production = _production()
    store = _store(tmp_path)
    store.bootstrap(profile_id="profile", project_id="project", project_identity="/work/project")
    store.begin_run("run")
    store.record_intent("run", "action", side_effecting=True)
    store.record_result("run", "action", status="SUCCEEDED")
    if corruption == "missing_tool_result":
        store.database.execute("DELETE FROM tool_results WHERE action_id = 'action'")
        expected = production.RecoveryIntegrityError
        repeated_status = "SUCCEEDED"
    else:
        expected = production.ActionBindingConflict
        repeated_status = "FAILED"
    with pytest.raises(expected):
        store.record_result("run", "action", status=repeated_status)


def test_result_cannot_cross_run_or_generation_binding(tmp_path: Path) -> None:
    production = _production()
    store = _store(tmp_path)
    store.bootstrap(profile_id="profile", project_id="project", project_identity="/work/project")
    store.begin_run("run-1")
    assert store.record_intent("run-1", "action", generation=3, side_effecting=True) is True
    store.database.execute("INSERT INTO threads(id, project_id) VALUES ('other-thread', 'project')")
    store.database.execute(
        "INSERT INTO runs(id, thread_id, state) VALUES ('run-2', 'other-thread', 'RUNNING')"
    )
    with pytest.raises(production.ActionBindingConflict):
        store.record_result("run-2", "action", generation=3, status="SUCCEEDED")
    with pytest.raises(production.ActionBindingConflict):
        store.record_result("run-1", "action", generation=4, status="SUCCEEDED")
    assert store.database.scalar("SELECT status FROM actions WHERE id = 'action'") == "PENDING"
    assert store.database.scalar("SELECT COUNT(*) FROM tool_results") == 0


def test_mixed_action_recovery_uses_the_most_severe_incomplete_boundary(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.bootstrap(profile_id="profile", project_id="project", project_identity="/work/project")
    store.begin_run("run")
    store.record_intent("run", "finished", side_effecting=False)
    store.record_result("run", "finished", status="SUCCEEDED")
    store.record_intent("run", "unknown", side_effecting=True)
    with store.database.transaction(immediate=True) as connection:
        store.journal.record(connection, "run", "unknown", "EFFECT", side_effecting=True)
    recovered = store.recover_run("run")
    assert recovered.state == "UNKNOWN"
    assert recovered.replay_permitted is False
    assert recovered.reconciliation_required is True


@pytest.mark.parametrize("corruption", ["orphan", "effect_after_result"])
def test_invalid_journal_prefix_fails_closed(tmp_path: Path, corruption: str) -> None:
    production = _production()
    store = _store(tmp_path)
    store.bootstrap(profile_id="profile", project_id="project", project_identity="/work/project")
    store.begin_run("run")
    if corruption == "orphan":
        store.database.execute(
            "INSERT INTO action_journal(run_id, action_id, phase, side_effecting) "
            "VALUES ('run', 'missing-action', 'INTENT', 1)"
        )
    else:
        store.record_intent("run", "action", side_effecting=True)
        store.record_result("run", "action", status="SUCCEEDED")
        store.database.execute(
            "INSERT INTO action_journal(run_id, action_id, phase, side_effecting) "
            "VALUES ('run', 'action', 'EFFECT', 1)"
        )
    with pytest.raises(production.RecoveryIntegrityError):
        store.recover_run("run")


@pytest.mark.parametrize("corruption", ["missing_tool_result", "action_status_drift"])
def test_recovery_rejects_result_boundary_storage_gaps(tmp_path: Path, corruption: str) -> None:
    production = _production()
    store = _store(tmp_path)
    store.bootstrap(profile_id="profile", project_id="project", project_identity="/work/project")
    store.begin_run("run")
    store.record_intent("run", "action", side_effecting=True)
    store.record_result("run", "action", status="SUCCEEDED")
    if corruption == "missing_tool_result":
        store.database.execute("DELETE FROM tool_results WHERE action_id = 'action'")
    else:
        store.database.execute("UPDATE actions SET status = 'FAILED' WHERE id = 'action'")
    with pytest.raises(production.RecoveryIntegrityError, match="RESULT_PERSISTENCE"):
        store.recover_run("run")


@pytest.mark.parametrize(
    "fault_point",
    [
        "intent_after_journal",
        "intent_after_action",
        "result_after_journal",
        "result_after_action",
        "result_after_tool_result",
    ],
)
def test_action_boundary_statement_faults_leave_no_half_transaction(
    tmp_path: Path, fault_point: str
) -> None:
    audit = importlib.import_module("yagcode.persistence.audit")
    production = _production()
    armed = False

    def hook(point: str) -> None:
        if armed and point == fault_point:
            raise RuntimeError(f"SENTINEL_{point}")

    store = production.PersistenceStore(
        tmp_path,
        anchors=audit.InMemoryAnchorStore({"profile": b"test-anchor"}),
        statement_hook=hook,
    )
    store.bootstrap(profile_id="profile", project_id="project", project_identity="/work/project")
    store.begin_run("run")
    if fault_point.startswith("result_"):
        store.record_intent("run", "action", side_effecting=True)
    armed = True
    with pytest.raises(RuntimeError, match=fault_point):
        if fault_point.startswith("intent_"):
            store.record_intent("run", "action", side_effecting=True)
        else:
            store.record_result("run", "action", status="SUCCEEDED")
    if fault_point.startswith("intent_"):
        assert store.database.scalar("SELECT COUNT(*) FROM actions") == 0
        assert store.database.scalar("SELECT COUNT(*) FROM action_journal") == 0
    else:
        assert store.database.scalar("SELECT status FROM actions WHERE id = 'action'") == "PENDING"
        assert store.database.scalar(
            "SELECT COUNT(*) FROM action_journal WHERE phase = 'RESULT'"
        ) == 0
        assert store.database.scalar("SELECT COUNT(*) FROM tool_results") == 0

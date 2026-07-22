"""Test-owned database oracles for the persistence contract."""

from __future__ import annotations

import importlib
import sqlite3
import threading
from pathlib import Path

import pytest


def _production() -> object:
    return importlib.import_module("yagcode.persistence.database")


def test_owned_sqlite_oracle_rejects_cross_profile_reference() -> None:
    """The oracle is deliberately independent of the production schema."""
    import sqlite3

    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        "CREATE TABLE profiles(id TEXT PRIMARY KEY);"
        "CREATE TABLE projects(id TEXT PRIMARY KEY, profile_id TEXT REFERENCES profiles(id));"
        "CREATE TABLE artifacts(id TEXT PRIMARY KEY, profile_id TEXT REFERENCES profiles(id));"
        "CREATE TABLE owned_refs(project_id TEXT REFERENCES projects(id), artifact_id TEXT REFERENCES artifacts(id));"
    )
    connection.execute("INSERT INTO profiles VALUES ('a')")
    connection.execute("INSERT INTO profiles VALUES ('b')")
    connection.execute("INSERT INTO projects VALUES ('p', 'a')")
    connection.execute("INSERT INTO artifacts VALUES ('x', 'b')")
    # Foreign keys alone cannot encode this composite ownership relation.
    project_profile = connection.execute(
        "SELECT profile_id FROM projects WHERE id = 'p'"
    ).fetchone()[0]
    artifact_profile = connection.execute(
        "SELECT profile_id FROM artifacts WHERE id = 'x'"
    ).fetchone()[0]
    assert project_profile != artifact_profile


def test_database_enables_wal_foreign_keys_and_one_active_run(tmp_path: Path) -> None:
    production = _production()
    db = production.Database(tmp_path / "state.sqlite3")
    try:
        db.create_profile("profile")
        db.create_project("project", "profile", "/work/project")
        assert str(db.scalar("PRAGMA journal_mode")).lower() == "wal"
        assert db.scalar("PRAGMA foreign_keys") == 1
        db.create_active_run(project_id="project", run_id="run-1")
        with pytest.raises(production.ActiveRunConflict):
            db.create_active_run(project_id="project", run_id="run-2")
    finally:
        db.close()


def test_transaction_is_immediate_and_rolls_back(tmp_path: Path) -> None:
    production = _production()
    db = production.Database(tmp_path / "state.sqlite3")
    try:
        db.execute("CREATE TABLE probe(value TEXT NOT NULL)")
        with pytest.raises(RuntimeError):
            with db.transaction(immediate=True) as connection:
                connection.execute("INSERT INTO probe VALUES ('discard')")
                raise RuntimeError("fault")
        assert db.scalar("SELECT COUNT(*) FROM probe") == 0
    finally:
        db.close()


def test_schema_contains_all_spec_entities_and_memory_fts(tmp_path: Path) -> None:
    production = _production()
    db = production.Database(tmp_path / "state.sqlite3")
    try:
        names = {
            row[0]
            for row in db.query("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
        }
        required = {
            "profiles", "agent_config_versions", "provider_configs", "projects", "threads", "runs",
            "actions", "tool_results", "checkpoints", "artifacts", "validation_results",
            "approval_rules", "privacy_grants", "privacy_preview_artifacts", "credential_refs",
            "egress_requests", "memory_items", "promotion_candidates", "integration_attempts",
            "integration_entries", "audit_events", "active_project_locks", "memory_items_fts",
        }
        assert required <= names
        db.create_profile("profile")
        db.execute(
            "INSERT INTO audit_events(profile_id, sequence, event_type, result, prev_digest, event_digest, schema_version) "
            "VALUES ('profile', 1, 'INTENT', 'RECORDED', '', 'digest', 1)"
        )
        with pytest.raises(sqlite3.IntegrityError, match="AUDIT_APPEND_ONLY"):
            db.execute("UPDATE audit_events SET result = 'TAMPERED'")
        credential_columns = {row[1] for row in db.query("PRAGMA table_info(credential_refs)")}
        assert "secret" not in credential_columns
        assert "value" not in credential_columns
    finally:
        db.close()


def test_cross_profile_project_and_grant_insertions_fail_closed(tmp_path: Path) -> None:
    production = _production()
    db = production.Database(tmp_path / "state.sqlite3")
    try:
        for profile in ("a", "b"):
            db.create_profile(profile)
        db.create_project("project-a", "a", "/a")
        db.create_project("project-b", "b", "/b")
        db.execute("INSERT INTO threads(id, project_id) VALUES ('thread-b', 'project-b')")
        db.execute("INSERT INTO runs(id, thread_id, state) VALUES ('run-b', 'thread-b', 'RUNNING')")
        db.execute(
            "INSERT INTO actions(id, run_id, sequence, kind, payload_hash, policy_decision, status) "
            "VALUES ('action-b', 'run-b', 1, 'read_text', 'hash', 'ALLOW', 'PENDING')"
        )
        db.execute("INSERT INTO privacy_grants VALUES ('grant-b', 'b', '/', 'source', 'purpose', 'v1', 'now', NULL)")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO approval_rules VALUES ('rule', 'a', 'project-b', 'k', 'v', 's', '/', 'r', 'h', 1, 'p')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO privacy_preview_artifacts VALUES ('preview', 'a', 'grant-b', 'r', 's', 'raw', 'redacted', 'c', 'p', 'now')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO egress_requests VALUES ('egress', 'a', 'project-b', NULL, 0, NULL, 'https://x', 'POST', 'p', 'h', '[]', '[]', NULL)")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO egress_requests VALUES ('egress-run', 'a', 'project-a', 'run-b', 0, NULL, 'https://x', 'POST', 'p', 'h', '[]', '[]', NULL)")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO egress_requests VALUES ('egress-action', 'a', 'project-a', NULL, 0, 'action-b', 'https://x', 'POST', 'p', 'h', '[]', '[]', NULL)")
        db.execute("INSERT INTO approval_rules VALUES ('rule-b', 'b', 'project-b', 'k', 'v', 's', '/', 'r', 'h', 1, 'p')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE approval_rules SET profile_id = 'a' WHERE id = 'rule-b'")
        db.execute("INSERT INTO privacy_preview_artifacts VALUES ('preview-b', 'b', 'grant-b', 'r', 's', 'raw', 'redacted', 'c', 'p', 'now')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE privacy_preview_artifacts SET profile_id = 'a' WHERE id = 'preview-b'")
    finally:
        db.close()


def test_independent_connections_contend_for_one_project_lock(tmp_path: Path) -> None:
    production = _production()
    setup = production.Database(tmp_path / "state.sqlite3")
    setup.create_profile("profile")
    setup.create_project("project", "profile", "/same")
    setup.close()
    barrier = threading.Barrier(2)
    results: list[str] = []

    def contender(run_id: str) -> None:
        db = production.Database(tmp_path / "state.sqlite3")
        try:
            barrier.wait()
            db.create_active_run(project_id="project", run_id=run_id)
            results.append("won")
        except production.ActiveRunConflict:
            results.append("conflict")
        finally:
            db.close()

    threads = [threading.Thread(target=contender, args=(f"run-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["conflict", "won"]
    final = production.Database(tmp_path / "state.sqlite3")
    try:
        assert final.scalar("SELECT COUNT(*) FROM runs") == 1
        assert final.scalar("SELECT COUNT(*) FROM active_project_locks") == 1
    finally:
        final.close()


def test_duplicate_run_identifier_is_normalized_and_rolls_back(tmp_path: Path) -> None:
    production = _production()
    db = production.Database(tmp_path / "state.sqlite3")
    try:
        db.create_profile("profile")
        db.create_project("project-a", "profile", "/a")
        db.create_project("project-b", "profile", "/b")
        db.create_active_run(project_id="project-a", run_id="same-run")
        with pytest.raises(production.ActiveRunConflict):
            db.create_active_run(project_id="project-b", run_id="same-run")
        assert db.scalar("SELECT COUNT(*) FROM runs WHERE id = 'same-run'") == 1
        assert db.scalar("SELECT COUNT(*) FROM active_project_locks") == 1
    finally:
        db.close()


def test_bootstrap_project_identity_is_idempotent_but_not_mutable(tmp_path: Path) -> None:
    production = _production()
    db = production.Database(tmp_path / "state.sqlite3")
    try:
        db.create_profile("profile")
        db.create_project("project", "profile", "/same")
        db.create_project("project", "profile", "/same")
        with pytest.raises(Exception, match="PROJECT_IDENTITY_CONFLICT"):
            db.create_project("project", "profile", "/different")
        db.create_profile("other")
        with pytest.raises(Exception, match="PROJECT_IDENTITY_CONFLICT"):
            db.create_project("project", "other", "/same")
    finally:
        db.close()

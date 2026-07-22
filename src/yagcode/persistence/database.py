"""SQLite bootstrap and transaction boundary; connections are never shared across threads."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence


class ActiveRunConflict(RuntimeError):
    """A project already owns a durable active run lock."""


class ProjectIdentityConflict(RuntimeError):
    """An existing project identifier is bound to different immutable ownership data."""


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path, isolation_level=None, check_same_thread=True)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = FULL")
        schema = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
        self.connection.executescript(schema)

    def close(self) -> None:
        self.connection.close()

    def execute(self, sql: str, parameters: Sequence[object] = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, parameters)

    def query(self, sql: str, parameters: Sequence[object] = ()) -> list[tuple[object, ...]]:
        return self.connection.execute(sql, parameters).fetchall()

    def scalar(self, sql: str, parameters: Sequence[object] = ()) -> object:
        row = self.connection.execute(sql, parameters).fetchone()
        if row is None:
            raise LookupError("query returned no row")
        return row[0]

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        self.connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield self.connection
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def create_profile(self, profile_id: str) -> None:
        self.execute("INSERT OR IGNORE INTO profiles(id) VALUES (?)", (profile_id,))

    def create_project(self, project_id: str, profile_id: str, project_identity: str) -> None:
        existing = self.connection.execute(
            "SELECT profile_id, canonical_root FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if existing is not None:
            if existing != (profile_id, project_identity):
                raise ProjectIdentityConflict("PROJECT_IDENTITY_CONFLICT")
            return
        try:
            self.execute(
                "INSERT INTO projects(id, profile_id, canonical_root) VALUES (?, ?, ?)",
                (project_id, profile_id, project_identity),
            )
        except sqlite3.IntegrityError as error:
            raise ProjectIdentityConflict("PROJECT_IDENTITY_CONFLICT") from error

    def create_active_run(self, *, project_id: str, run_id: str) -> None:
        with self.transaction(immediate=True) as connection:
            project = connection.execute(
                "SELECT canonical_root FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise LookupError("unknown project")
            thread_id = f"persistence:{project_id}"
            try:
                connection.execute(
                    "INSERT OR IGNORE INTO threads(id, project_id) VALUES (?, ?)", (thread_id, project_id)
                )
                connection.execute(
                    "INSERT INTO runs(id, thread_id, state) VALUES (?, ?, 'RUNNING')", (run_id, thread_id)
                )
                connection.execute(
                    "INSERT INTO active_project_locks(project_identity, project_id, run_id) VALUES (?, ?, ?)",
                    (project[0], project_id, run_id),
                )
            except sqlite3.IntegrityError as error:
                raise ActiveRunConflict("ACTIVE_PROJECT_RUN_EXISTS") from error


__all__ = ["ActiveRunConflict", "Database", "ProjectIdentityConflict"]

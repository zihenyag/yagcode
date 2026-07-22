"""Intent/result journal rules used by recovery; it never replays a side effect."""

from __future__ import annotations

import sqlite3

from .database import Database


class ActionJournal:
    def __init__(self, database: Database) -> None:
        self.database = database

    def record(
        self, connection: sqlite3.Connection, run_id: str, action_id: str, phase: str, *, side_effecting: bool
    ) -> bool:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO action_journal(run_id, action_id, phase, side_effecting) VALUES (?, ?, ?, ?)",
            (run_id, action_id, phase, int(side_effecting)),
        )
        return cursor.rowcount == 1

    def phases(self, run_id: str, action_id: str) -> set[str]:
        return {
            str(row[0])
            for row in self.database.query(
                "SELECT phase FROM action_journal WHERE run_id = ? AND action_id = ?", (run_id, action_id)
            )
        }

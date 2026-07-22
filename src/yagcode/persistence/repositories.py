"""Small repository facade for action-boundary persistence and deterministic recovery."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, cast

from .artifacts import ArtifactStore
from .audit import AnchorStore, AuditLog
from .database import ActiveRunConflict, Database
from .journal import ActionJournal


@dataclass(frozen=True)
class RecoveryResult:
    state: str
    replay_permitted: bool
    reconciliation_required: bool


class ActionBindingConflict(RuntimeError):
    """An action identifier was reused with a different run or generation."""


class RecoveryIntegrityError(RuntimeError):
    """The persisted action journal is not a valid prefix of the boundary protocol."""


class PersistenceStore:
    def __init__(
        self, root: Path, *, anchors: AnchorStore, statement_hook: Callable[[str], None] | None = None
    ) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.database = Database(root / "state.sqlite3")
        self.artifacts = ArtifactStore(root / "artifacts", database=self.database)
        self.audit = AuditLog(self.database, anchors)
        self.journal = ActionJournal(self.database)
        self._statement_hook = statement_hook
        self._profile_id: str | None = None
        self._project_id: str | None = None

    def bootstrap(self, *, profile_id: str, project_id: str, project_identity: str) -> None:
        self.database.create_profile(profile_id)
        self.database.create_project(project_id, profile_id, project_identity)
        self._profile_id = profile_id
        self._project_id = project_id

    def begin_run(self, run_id: str) -> None:
        if self._project_id is None:
            raise RuntimeError("PERSISTENCE_NOT_BOOTSTRAPPED")
        self.database.create_active_run(project_id=self._project_id, run_id=run_id)

    def close(self) -> None:
        self.database.close()

    def record_intent(
        self,
        run_id: str,
        action_id: str,
        *,
        generation: int = 0,
        side_effecting: bool,
    ) -> bool:
        if generation < 0:
            raise ActionBindingConflict("ACTION_GENERATION_INVALID")
        with self.database.transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT run_id, generation FROM actions WHERE id = ?", (action_id,)
            ).fetchone()
            if existing is not None and existing != (run_id, generation):
                raise ActionBindingConflict("ACTION_BINDING_MISMATCH")
            persisted_intents = connection.execute(
                "SELECT run_id, side_effecting FROM action_journal "
                "WHERE action_id = ? AND phase = 'INTENT'",
                (action_id,),
            ).fetchall()
            if (existing is None) != (not persisted_intents) or len(persisted_intents) > 1:
                raise RecoveryIntegrityError("ACTION_INTENT_PERSISTENCE_INCONSISTENT")
            if existing is not None:
                persisted_run_id, persisted_side_effecting = persisted_intents[0]
                if persisted_run_id != run_id:
                    raise RecoveryIntegrityError("ACTION_INTENT_PERSISTENCE_INCONSISTENT")
                if bool(persisted_side_effecting) != side_effecting:
                    raise ActionBindingConflict("ACTION_INTENT_MISMATCH")
                inserted = False
            else:
                inserted = self.journal.record(
                    connection,
                    run_id,
                    action_id,
                    "INTENT",
                    side_effecting=side_effecting,
                )
                if not inserted:
                    raise RecoveryIntegrityError("ACTION_INTENT_PERSISTENCE_INCONSISTENT")
                self._fault("intent_after_journal")
                self._insert_action(connection, run_id, action_id, generation)
                self._fault("intent_after_action")
        self._audit(
            run_id,
            action_id,
            "INTENT" if inserted else "STALE_INTENT",
            "RECORDED" if inserted else "IGNORED",
        )
        return inserted

    def record_result(
        self,
        run_id: str,
        action_id: str,
        *,
        generation: int = 0,
        status: str,
    ) -> bool:
        if status not in {"SUCCEEDED", "FAILED", "DENIED", "UNKNOWN"}:
            raise ValueError("TOOL_RESULT_STATUS_INVALID")
        with self.database.transaction(immediate=True) as connection:
            binding = connection.execute(
                "SELECT run_id, generation, status FROM actions WHERE id = ?", (action_id,)
            ).fetchone()
            if binding is None or binding[:2] != (run_id, generation):
                raise ActionBindingConflict("ACTION_BINDING_MISMATCH")
            persisted_results = connection.execute(
                "SELECT run_id FROM action_journal WHERE action_id = ? AND phase = 'RESULT'",
                (action_id,),
            ).fetchall()
            tool_result = connection.execute(
                "SELECT status FROM tool_results WHERE action_id = ?", (action_id,)
            ).fetchone()
            if len(persisted_results) > 1 or (
                persisted_results and persisted_results[0][0] != run_id
            ):
                raise RecoveryIntegrityError("ACTION_RESULT_PERSISTENCE_INCONSISTENT")
            if persisted_results:
                if tool_result is None or binding[2] != tool_result[0]:
                    raise RecoveryIntegrityError("ACTION_RESULT_PERSISTENCE_INCONSISTENT")
                if binding[2] != status:
                    raise ActionBindingConflict("ACTION_RESULT_MISMATCH")
                inserted = False
            else:
                if tool_result is not None or binding[2] != "PENDING":
                    raise RecoveryIntegrityError("ACTION_RESULT_PERSISTENCE_INCONSISTENT")
                inserted = self.journal.record(
                    connection,
                    run_id,
                    action_id,
                    "RESULT",
                    side_effecting=False,
                )
                if not inserted:
                    raise RecoveryIntegrityError("ACTION_RESULT_PERSISTENCE_INCONSISTENT")
                self._fault("result_after_journal")
                connection.execute(
                    "UPDATE actions SET status = ? WHERE id = ? AND run_id = ? AND generation = ?",
                    (status, action_id, run_id, generation),
                )
                self._fault("result_after_action")
                connection.execute(
                    "INSERT INTO tool_results(action_id, status, category, reason_code, side_effect_state, retryable) "
                    "VALUES (?, ?, 'RECOVERY', 'RECORDED', 'NONE', 0)", (action_id, status),
                )
                self._fault("result_after_tool_result")
        self._audit(
            run_id,
            action_id,
            "RESULT" if inserted else "STALE_RESULT",
            "RECORDED" if inserted else "IGNORED",
        )
        return inserted

    def simulate_action_crash(self, run_id: str, *, action_id: str, crash_point: str) -> None:
        if crash_point == "before_intent":
            return
        self.record_intent(run_id, action_id, side_effecting=True)
        if crash_point == "after_intent":
            return
        with self.database.transaction(immediate=True) as connection:
            self.journal.record(connection, run_id, action_id, "EFFECT", side_effecting=True)
        if crash_point == "after_effect":
            return
        if crash_point == "after_result":
            self.record_result(run_id, action_id, status="SUCCEEDED")
            return
        raise ValueError("CRASH_POINT_INVALID")

    def recover_run(self, run_id: str) -> RecoveryResult:
        action_rows = self.database.query(
            "SELECT id, status FROM actions WHERE run_id = ? ORDER BY sequence", (run_id,)
        )
        journal_rows = self.database.query(
            "SELECT action_id, phase, side_effecting FROM action_journal "
            "WHERE run_id = ? ORDER BY id",
            (run_id,),
        )
        action_ids = tuple(str(row[0]) for row in action_rows)
        action_statuses = {str(row[0]): str(row[1]) for row in action_rows}
        tool_statuses = {
            str(row[0]): str(row[1])
            for row in self.database.query(
                "SELECT tool_results.action_id, tool_results.status FROM tool_results "
                "JOIN actions ON actions.id = tool_results.action_id WHERE actions.run_id = ?",
                (run_id,),
            )
        }
        known = set(action_ids)
        if any(str(row[0]) not in known for row in journal_rows):
            raise RecoveryIntegrityError("ORPHAN_JOURNAL_ENTRY")
        if not action_ids:
            if journal_rows:
                raise RecoveryIntegrityError("ORPHAN_JOURNAL_ENTRY")
            return RecoveryResult("CREATED", False, False)
        phases: dict[str, list[tuple[str, bool]]] = {action_id: [] for action_id in action_ids}
        for action_id, phase, side_effecting in journal_rows:
            phases[str(action_id)].append((str(phase), bool(side_effecting)))
        valid_orders = {
            ("INTENT",),
            ("INTENT", "EFFECT"),
            ("INTENT", "RESULT"),
            ("INTENT", "EFFECT", "RESULT"),
        }
        for action_id in action_ids:
            entries = phases[action_id]
            order = tuple(phase for phase, _ in entries)
            if order not in valid_orders:
                raise RecoveryIntegrityError("ACTION_JOURNAL_ORDER_INVALID")
            intent_side_effecting = entries[0][1]
            if any(phase == "EFFECT" and (not side_effecting or not intent_side_effecting) for phase, side_effecting in entries):
                raise RecoveryIntegrityError("ACTION_JOURNAL_EFFECT_INVALID")
            if any(phase == "RESULT" and side_effecting for phase, side_effecting in entries):
                raise RecoveryIntegrityError("ACTION_JOURNAL_RESULT_INVALID")
            if "RESULT" in order:
                if tool_statuses.get(action_id) != action_statuses[action_id]:
                    raise RecoveryIntegrityError("ACTION_RESULT_PERSISTENCE_INCONSISTENT")
            elif action_id in tool_statuses or action_statuses[action_id] != "PENDING":
                raise RecoveryIntegrityError("ACTION_RESULT_PERSISTENCE_INCONSISTENT")
        orders = tuple(tuple(phase for phase, _ in phases[action_id]) for action_id in action_ids)
        if any("EFFECT" in current and "RESULT" not in current for current in orders):
            return RecoveryResult("UNKNOWN", False, True)
        if all("RESULT" in current for current in orders):
            return RecoveryResult("FINISHED", False, False)
        return RecoveryResult("INTERRUPTED", False, False)

    def effect_count(self, action_id: str) -> int:
        return cast(
            int,
            self.database.scalar(
                "SELECT COUNT(*) FROM action_journal WHERE action_id = ? AND phase = 'EFFECT'", (action_id,)
            ),
        )

    def stale_audit_count(self, action_id: str) -> int:
        row = self.database.query(
            "SELECT COUNT(*) FROM audit_events WHERE action_id = ? AND event_type LIKE 'STALE_%'",
            (action_id,),
        )[0]
        return cast(int, row[0])

    def _insert_action(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        action_id: str,
        generation: int,
    ) -> None:
        row = connection.execute(
            "SELECT COUNT(*) + 1 FROM actions WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RecoveryIntegrityError("ACTION_SEQUENCE_UNAVAILABLE")
        sequence = cast(int, row[0])
        connection.execute(
            "INSERT INTO actions(id, run_id, sequence, generation, kind, payload_hash, policy_decision, status) "
            "VALUES (?, ?, ?, ?, 'recovery', 'opaque', 'RECORDED', 'PENDING')",
            (action_id, run_id, sequence, generation),
        )

    def _audit(self, run_id: str, action_id: str, event_type: str, result: str) -> None:
        if self._profile_id is not None:
            self.audit.append(
                self._profile_id,
                run_id=run_id,
                action_id=action_id,
                event_type=event_type,
                result=result,
            )

    def _fault(self, point: str) -> None:
        if self._statement_hook is not None:
            self._statement_hook(point)


__all__ = [
    "ActionBindingConflict",
    "ActiveRunConflict",
    "PersistenceStore",
    "RecoveryIntegrityError",
    "RecoveryResult",
]

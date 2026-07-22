"""Append-only audit records with an injected, durable anchor store."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol, cast

from .database import Database


SCHEMA_VERSION = 1
_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_OPAQUE_REF_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$"
)
_AUDIT_LOCKS_GUARD = threading.Lock()
_AUDIT_LOCKS: dict[tuple[Path, str], threading.RLock] = {}


class AuditIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuditAnchor:
    profile_id: str
    sequence: int
    digest: str
    schema_version: int = SCHEMA_VERSION


class AnchorStore(Protocol):
    def key_for(self, profile_id: str) -> bytes: ...
    def get_anchor(self, profile_id: str) -> AuditAnchor | None: ...
    def set_anchor(self, anchor: AuditAnchor) -> None: ...


class InMemoryAnchorStore:
    """Test-only injected anchor store; production must pass an OS-keyring adapter."""

    def __init__(self, keys: dict[str, bytes]) -> None:
        self._keys = dict(keys)
        self._anchors: dict[str, AuditAnchor] = {}

    def key_for(self, profile_id: str) -> bytes:
        try:
            return self._keys[profile_id]
        except KeyError as error:
            raise AuditIntegrityError("AUDIT_KEY_MISSING") from error

    def get_anchor(self, profile_id: str) -> AuditAnchor | None:
        return self._anchors.get(profile_id)

    def set_anchor(self, anchor: AuditAnchor) -> None:
        self._anchors[anchor.profile_id] = anchor


def _canonical(
    *,
    profile_id: str,
    sequence: int,
    run_id: str | None,
    action_id: str | None,
    event_type: str,
    decision_ref: str | None,
    result: str,
    content_digest: str | None,
    prev_digest: str,
    created_at: str,
) -> bytes:
    return json.dumps(
        {
            "action_id": action_id,
            "content_digest": content_digest,
            "created_at": created_at,
            "decision_ref": decision_ref,
            "event_type": event_type,
            "prev_digest": prev_digest,
            "profile_id": profile_id,
            "result": result,
            "run_id": run_id,
            "schema_version": SCHEMA_VERSION,
            "sequence": sequence,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _validate_fields(
    event_type: object,
    result: object,
    decision_ref: object,
    content_digest: object,
    run_id: object,
    action_id: object,
) -> None:
    if not isinstance(event_type, str) or _CODE_PATTERN.fullmatch(event_type) is None:
        raise AuditIntegrityError("AUDIT_EVENT_TYPE_INVALID")
    if not isinstance(result, str) or _CODE_PATTERN.fullmatch(result) is None:
        raise AuditIntegrityError("AUDIT_RESULT_INVALID")
    if decision_ref is not None and (
        not isinstance(decision_ref, str)
        or _OPAQUE_REF_PATTERN.fullmatch(decision_ref) is None
    ):
        raise AuditIntegrityError("AUDIT_DECISION_REF_INVALID")
    if content_digest is not None and (
        not isinstance(content_digest, str)
        or _OPAQUE_REF_PATTERN.fullmatch(content_digest) is None
    ):
        raise AuditIntegrityError("AUDIT_CONTENT_DIGEST_INVALID")
    for value, code in (
        (run_id, "AUDIT_RUN_ID_INVALID"),
        (action_id, "AUDIT_ACTION_ID_INVALID"),
    ):
        if value is not None and (
            not isinstance(value, str)
            or not 1 <= len(value) <= 128
            or "\x00" in value
        ):
            raise AuditIntegrityError(code)


def _validate_created_at(value: object) -> None:
    if not isinstance(value, str) or _UTC_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise AuditIntegrityError("AUDIT_CREATED_AT_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise AuditIntegrityError("AUDIT_CREATED_AT_INVALID") from error
    if parsed.tzinfo != timezone.utc or parsed.isoformat(timespec="microseconds") != value:
        raise AuditIntegrityError("AUDIT_CREATED_AT_INVALID")


def _created_at(clock: Callable[[], datetime]) -> str:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AuditIntegrityError("AUDIT_CLOCK_NOT_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _profile_lock(database_path: Path, profile_id: str) -> threading.RLock:
    key = (database_path.resolve(), profile_id)
    with _AUDIT_LOCKS_GUARD:
        return _AUDIT_LOCKS.setdefault(key, threading.RLock())


class AuditLog:
    def __init__(
        self,
        database: Database,
        anchors: AnchorStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = database
        self.anchors = anchors
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def append(
        self,
        profile_id: str,
        *,
        run_id: str | None = None,
        action_id: str | None = None,
        event_type: str,
        result: str,
        decision_ref: str | None = None,
        content_digest: str | None = None,
    ) -> AuditAnchor:
        with _profile_lock(self.database.path, profile_id):
            return self._append_locked(
                profile_id,
                run_id=run_id,
                action_id=action_id,
                event_type=event_type,
                result=result,
                decision_ref=decision_ref,
                content_digest=content_digest,
            )

    def _append_locked(
        self,
        profile_id: str,
        *,
        run_id: str | None,
        action_id: str | None,
        event_type: str,
        result: str,
        decision_ref: str | None,
        content_digest: str | None,
    ) -> AuditAnchor:
        _validate_fields(
            event_type,
            result,
            decision_ref,
            content_digest,
            run_id,
            action_id,
        )
        tail = self._verified_tail(profile_id)
        sequence = tail.sequence + 1
        created_at = _created_at(self.clock)
        digest = hmac.new(
            self.anchors.key_for(profile_id),
            _canonical(
                profile_id=profile_id,
                sequence=sequence,
                run_id=run_id,
                action_id=action_id,
                event_type=event_type,
                decision_ref=decision_ref,
                result=result,
                content_digest=content_digest,
                prev_digest=tail.digest,
                created_at=created_at,
            ),
            hashlib.sha256,
        ).hexdigest()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO audit_events"
                "(profile_id, sequence, run_id, action_id, event_type, decision_ref, result, "
                "content_digest, prev_digest, event_digest, schema_version, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    profile_id,
                    sequence,
                    run_id,
                    action_id,
                    event_type,
                    decision_ref,
                    result,
                    content_digest,
                    tail.digest,
                    digest,
                    SCHEMA_VERSION,
                    created_at,
                ),
            )
        next_anchor = AuditAnchor(profile_id, sequence, digest)
        self.anchors.set_anchor(next_anchor)
        return next_anchor

    def verify(self, profile_id: str) -> bool:
        with _profile_lock(self.database.path, profile_id):
            self._verified_tail(profile_id)
        return True

    def _verified_tail(self, profile_id: str) -> AuditAnchor:
        rows = self.database.query(
            "SELECT sequence, run_id, action_id, event_type, decision_ref, result, content_digest, "
            "prev_digest, event_digest, schema_version, created_at "
            "FROM audit_events WHERE profile_id = ? ORDER BY sequence",
            (profile_id,),
        )
        anchor = self.anchors.get_anchor(profile_id)
        if anchor is not None:
            if anchor.profile_id != profile_id:
                raise AuditIntegrityError("AUDIT_ANCHOR_PROFILE_MISMATCH")
            if anchor.schema_version != SCHEMA_VERSION:
                raise AuditIntegrityError("AUDIT_ANCHOR_SCHEMA_MISMATCH")
            if anchor.sequence < 0:
                raise AuditIntegrityError("AUDIT_ANCHOR_SEQUENCE_INVALID")
        if not rows:
            if anchor is None:
                genesis = AuditAnchor(profile_id, 0, "")
                self.anchors.set_anchor(genesis)
                return genesis
            if anchor.sequence == 0 and anchor.digest == "":
                return anchor
            raise AuditIntegrityError("AUDIT_ROLLBACK_DETECTED")
        if anchor is None:
            raise AuditIntegrityError("AUDIT_ANCHOR_OR_HISTORY_MISSING")
        previous = ""
        matched_anchor = anchor.sequence == 0 and anchor.digest == ""
        for expected_sequence, row in enumerate(rows, start=1):
            (
                sequence,
                run_id,
                action_id,
                event_type,
                decision_ref,
                result,
                content_digest,
                prev_digest,
                event_digest,
                schema_version,
                created_at,
            ) = row
            if sequence != expected_sequence or schema_version != SCHEMA_VERSION or prev_digest != previous:
                raise AuditIntegrityError("AUDIT_CHAIN_DISCONTINUITY")
            _validate_fields(
                event_type,
                result,
                decision_ref,
                content_digest,
                run_id,
                action_id,
            )
            _validate_created_at(created_at)
            event_type_text = cast(str, event_type)
            result_text = cast(str, result)
            decision_ref_text = cast(str | None, decision_ref)
            content_digest_text = cast(str | None, content_digest)
            expected = hmac.new(
                self.anchors.key_for(profile_id),
                _canonical(
                    profile_id=profile_id,
                    sequence=cast(int, sequence),
                    run_id=cast(str | None, run_id),
                    action_id=cast(str | None, action_id),
                    event_type=event_type_text,
                    decision_ref=decision_ref_text,
                    result=result_text,
                    content_digest=content_digest_text,
                    prev_digest=previous,
                    created_at=cast(str, created_at),
                ),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, str(event_digest)):
                raise AuditIntegrityError("AUDIT_DIGEST_MISMATCH")
            previous = str(event_digest)
            if sequence == anchor.sequence:
                if not hmac.compare_digest(previous, anchor.digest):
                    raise AuditIntegrityError("AUDIT_ANCHOR_MISMATCH")
                matched_anchor = True
        if not matched_anchor:
            raise AuditIntegrityError("AUDIT_ROLLBACK_DETECTED")
        final = AuditAnchor(profile_id, len(rows), previous)
        if final.sequence > anchor.sequence:
            self.anchors.set_anchor(final)
        return final


__all__ = [
    "AnchorStore",
    "AuditAnchor",
    "AuditIntegrityError",
    "AuditLog",
    "InMemoryAnchorStore",
]

"""Apply accepted agent changes with preimage checks and conditional compensation."""

from __future__ import annotations

import hashlib
import os

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from yagcode.domain.states import IntegrationEvent, IntegrationState
from yagcode.domain.transitions import IntegrationGuards, transition_integration
from yagcode.git.compensation import CompensationError
from yagcode.git.integration_manifest import IntegrationEntryPlan, IntegrationManifest


FaultOperation = Literal["write", "rename", "chmod", "delete", "create", "replace", "verify"]
AfterApplyHook = Callable[[int], None]


@dataclass(frozen=True, slots=True)
class AcceptanceFault:
    operation: FaultOperation
    sequence: int

    def __post_init__(self) -> None:
        if self.operation not in {"write", "rename", "chmod", "delete", "create", "replace", "verify"}:
            raise ValueError("ACCEPTANCE_FAULT_OPERATION_INVALID")
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("ACCEPTANCE_FAULT_SEQUENCE_INVALID")


@dataclass(frozen=True, slots=True)
class AcceptResult:
    state: IntegrationState
    applied_sequences: tuple[int, ...] = ()
    compensated_sequences: tuple[int, ...] = ()
    live_write_count: int = 0
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class _Backup:
    path: Path
    exists: bool
    content: bytes | None
    mode: int | None
    destination: Path | None = None


@dataclass(frozen=True, slots=True)
class _AppliedEntry:
    plan: IntegrationEntryPlan
    backup: _Backup
    postimage_path: Path
    postimage_hash: str | None
    postimage_mode: int | None


class _InjectedAcceptanceFailure(RuntimeError):
    pass


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        return None
    return _sha256(path.read_bytes())


def _safe_relative(root: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or not pure.parts:
        raise ValueError("INTEGRATION_PATH_INVALID")
    if any(part in {"", ".", "..", ".git"} for part in pure.parts):
        raise ValueError("INTEGRATION_PATH_INVALID")
    candidate = root.joinpath(*pure.parts)
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as error:
        raise ValueError("INTEGRATION_PATH_INVALID") from error
    for parent in reversed(candidate.parents):
        if parent == root.parent:
            break
        if parent.exists() and parent.is_symlink():
            raise ValueError("INTEGRATION_PATH_SYMLINK")
        if parent == root:
            break
    if candidate.exists() and candidate.is_symlink():
        raise ValueError("INTEGRATION_PATH_SYMLINK")
    return candidate


class WorktreeIntegrationService:
    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve(strict=True)

    def accept(
        self,
        manifest: IntegrationManifest,
        *,
        fault: AcceptanceFault | None = None,
        after_apply: AfterApplyHook | None = None,
    ) -> AcceptResult:
        state = IntegrationState.PREPARING
        try:
            planned_paths = self._preflight(manifest)
        except ValueError as error:
            state = transition_integration(
                state,
                IntegrationEvent.CONFLICT_BEFORE_WRITE,
                IntegrationGuards(no_real_write=True),
            )
            return AcceptResult(state=state, reason_code=str(error), live_write_count=0)

        state = transition_integration(
            state,
            IntegrationEvent.PREPARE_SUCCEEDED,
            IntegrationGuards(manifest_persisted=True, locks_held=True),
        )
        state = transition_integration(
            state,
            IntegrationEvent.BEGIN_APPLY,
            IntegrationGuards(manifest_persisted=True, locks_held=True),
        )

        applied: list[_AppliedEntry] = []
        live_writes = 0
        try:
            for entry in manifest.entries:
                self._maybe_inject(fault, entry)
                applied_entry = self._apply_entry(entry, planned_paths[entry.sequence])
                applied.append(applied_entry)
                live_writes += 1
                if after_apply is not None:
                    after_apply(entry.sequence)
            self._maybe_inject_verify(fault)
        except (OSError, ValueError, _InjectedAcceptanceFailure) as error:
            state = transition_integration(
                state,
                IntegrationEvent.APPLY_FAILED,
                IntegrationGuards(failure_recorded=True),
            )
            compensated: list[int] = []
            try:
                for applied_entry in reversed(applied):
                    self._compensate_entry(applied_entry)
                    compensated.append(applied_entry.plan.sequence)
            except (OSError, CompensationError):
                state = transition_integration(
                    state,
                    IntegrationEvent.COMPENSATION_FAILED,
                    IntegrationGuards(recovery_evidence_recorded=True),
                )
                return AcceptResult(
                    state=state,
                    applied_sequences=tuple(entry.plan.sequence for entry in applied),
                    compensated_sequences=tuple(reversed(compensated)),
                    live_write_count=live_writes,
                    reason_code=str(error),
                )
            state = transition_integration(
                state,
                IntegrationEvent.COMPENSATION_SUCCEEDED,
                IntegrationGuards(all_preimages_verified=True),
            )
            return AcceptResult(
                state=state,
                applied_sequences=tuple(entry.plan.sequence for entry in applied),
                compensated_sequences=tuple(reversed(compensated)),
                live_write_count=live_writes,
                reason_code=str(error),
            )

        state = transition_integration(
            state,
            IntegrationEvent.APPLY_SUCCEEDED,
            IntegrationGuards(all_entries_applied=True),
        )
        if not self._all_postimages_match(applied):
            state = transition_integration(
                state,
                IntegrationEvent.VERIFICATION_FAILED,
                IntegrationGuards(failure_recorded=True),
            )
            return AcceptResult(
                state=state,
                applied_sequences=tuple(entry.plan.sequence for entry in applied),
                live_write_count=live_writes,
                reason_code="INTEGRATION_POSTIMAGE_MISMATCH",
            )
        state = transition_integration(
            state,
            IntegrationEvent.VERIFICATION_SUCCEEDED,
            IntegrationGuards(all_entries_verified=True, required_validations_passed=True),
        )
        return AcceptResult(
            state=state,
            applied_sequences=tuple(entry.plan.sequence for entry in applied),
            live_write_count=live_writes,
        )

    def _preflight(self, manifest: IntegrationManifest) -> dict[int, tuple[Path, Path | None]]:
        planned: dict[int, tuple[Path, Path | None]] = {}
        for entry in manifest.entries:
            path = _safe_relative(self._root, entry.path)
            destination = (
                _safe_relative(self._root, entry.destination_path)
                if entry.destination_path is not None
                else None
            )
            self._check_preimage(entry, path, destination)
            planned[entry.sequence] = (path, destination)
        return planned

    def _check_preimage(
        self, entry: IntegrationEntryPlan, path: Path, destination: Path | None
    ) -> None:
        observed = _file_hash(path)
        if entry.operation == "create":
            if observed is not None or entry.preimage_hash is not None:
                raise ValueError("INTEGRATION_PREIMAGE_CONFLICT")
        elif observed != entry.preimage_hash:
            raise ValueError("INTEGRATION_PREIMAGE_CONFLICT")
        if entry.operation in {"create", "replace"} and entry.content is not None:
            if _sha256(entry.content) != entry.planned_postimage_hash:
                raise ValueError("INTEGRATION_POSTIMAGE_HASH_MISMATCH")
        if entry.operation == "delete" and entry.planned_postimage_hash is not None:
            raise ValueError("INTEGRATION_DELETE_POSTIMAGE_INVALID")
        if entry.operation == "rename":
            if destination is None or destination.exists():
                raise ValueError("INTEGRATION_RENAME_DESTINATION_CONFLICT")
        if entry.operation != "create" and not path.exists():
            raise ValueError("INTEGRATION_TARGET_MISSING")
        if entry.operation in {"replace", "delete", "rename", "chmod"} and not path.is_file():
            raise ValueError("INTEGRATION_TARGET_NOT_FILE")

    def _maybe_inject(self, fault: AcceptanceFault | None, entry: IntegrationEntryPlan) -> None:
        if fault is not None and fault.sequence == entry.sequence:
            raise _InjectedAcceptanceFailure(f"INJECTED_{fault.operation.upper()}_FAILURE")

    def _maybe_inject_verify(self, fault: AcceptanceFault | None) -> None:
        if fault is not None and fault.operation == "verify":
            raise _InjectedAcceptanceFailure("INJECTED_VERIFY_FAILURE")

    def _backup(self, path: Path, destination: Path | None) -> _Backup:
        if path.exists():
            return _Backup(
                path=path,
                exists=True,
                content=path.read_bytes(),
                mode=path.stat().st_mode & 0o777,
                destination=destination,
            )
        return _Backup(path=path, exists=False, content=None, mode=None, destination=destination)

    def _apply_entry(
        self, entry: IntegrationEntryPlan, paths: tuple[Path, Path | None]
    ) -> _AppliedEntry:
        path, destination = paths
        backup = self._backup(path, destination)
        if entry.operation == "create":
            if entry.content is None:
                raise ValueError("INTEGRATION_CONTENT_REQUIRED")
            if not path.parent.exists():
                raise ValueError("INTEGRATION_PARENT_MISSING")
            path.write_bytes(entry.content)
            post_path = path
        elif entry.operation == "replace":
            if entry.content is None:
                raise ValueError("INTEGRATION_CONTENT_REQUIRED")
            path.write_bytes(entry.content)
            post_path = path
        elif entry.operation == "delete":
            path.unlink()
            post_path = path
        elif entry.operation == "rename":
            if destination is None:
                raise ValueError("INTEGRATION_DESTINATION_REQUIRED")
            os.replace(path, destination)
            post_path = destination
        elif entry.operation == "chmod":
            if entry.mode is None:
                raise ValueError("INTEGRATION_MODE_REQUIRED")
            path.chmod(entry.mode)
            post_path = path
        else:
            raise ValueError("INTEGRATION_OPERATION_INVALID")
        return _AppliedEntry(
            plan=entry,
            backup=backup,
            postimage_path=post_path,
            postimage_hash=_file_hash(post_path),
            postimage_mode=(post_path.stat().st_mode & 0o777) if post_path.exists() else None,
        )

    def _postimage_still_owned(self, applied: _AppliedEntry) -> bool:
        plan = applied.plan
        if plan.operation == "delete":
            return not applied.backup.path.exists()
        if plan.operation == "rename":
            return (
                not applied.backup.path.exists()
                and applied.postimage_path.exists()
                and _file_hash(applied.postimage_path) == applied.postimage_hash
            )
        if not applied.postimage_path.exists():
            return False
        if _file_hash(applied.postimage_path) != applied.postimage_hash:
            return False
        if plan.operation == "chmod":
            return (applied.postimage_path.stat().st_mode & 0o777) == applied.postimage_mode
        return True

    def _compensate_entry(self, applied: _AppliedEntry) -> None:
        if not self._postimage_still_owned(applied):
            raise CompensationError("POSTIMAGE_EXTERNALLY_MODIFIED")
        backup = applied.backup
        if applied.plan.operation == "rename":
            if backup.destination is None:
                raise CompensationError("RENAME_DESTINATION_MISSING")
            if backup.path.exists():
                raise CompensationError("RENAME_SOURCE_RECREATED")
            os.replace(backup.destination, backup.path)
        elif backup.exists:
            if backup.content is None:
                raise CompensationError("BACKUP_CONTENT_MISSING")
            backup.path.write_bytes(backup.content)
        elif backup.path.exists():
            backup.path.unlink()
        if backup.mode is not None and backup.path.exists():
            backup.path.chmod(backup.mode)

    def _all_postimages_match(self, entries: list[_AppliedEntry]) -> bool:
        return all(self._postimage_still_owned(entry) for entry in entries)


__all__ = ["AcceptanceFault", "AcceptResult", "WorktreeIntegrationService"]

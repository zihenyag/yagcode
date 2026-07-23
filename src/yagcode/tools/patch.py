"""Bounded structured patch application with same-directory staged replacement."""

from __future__ import annotations

import hashlib
import os
import secrets
from collections.abc import Callable, Mapping
from pathlib import Path

from yagcode.domain.actions import ApplyPatchAction
from yagcode.domain.results import SideEffectState, ToolResult, ToolStatus
from yagcode.policy.paths import PathSecurityError, SecurePathResolver


StagePathFactory = Callable[[Path], Path]


def _result(
    action: ApplyPatchAction,
    status: ToolStatus,
    category: str,
    reason: str,
    side: SideEffectState,
) -> ToolResult:
    return ToolResult(
        action_id=action.action_id,
        status=status,
        category=category,
        reason_code=reason,
        side_effect_state=side,
        retryable=False,
    )


def _apply(source: bytes, action: ApplyPatchAction) -> bytes | None:
    text = source.decode("utf-8", errors="strict")
    lines = text.splitlines(keepends=True)
    offset = 0
    for hunk in action.payload.hunks:
        start = hunk.start_line - 1 + offset
        stop = start + hunk.delete_line_count
        if start < 0 or stop > len(lines):
            return None
        if "".join(lines[start:stop]) != hunk.expected_text:
            return None
        replacement = hunk.replacement_text.splitlines(keepends=True)
        lines[start:stop] = replacement
        offset += len(replacement) - hunk.delete_line_count
    return "".join(lines).encode("utf-8")


def _default_stage_path(target: Path) -> Path:
    return target.with_name(f".{target.name}.yagcode-stage-{secrets.token_hex(12)}")


def _fsync_parent(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def apply_action(
    action: ApplyPatchAction,
    *,
    roots: Mapping[str, Path],
    stage_path_factory: StagePathFactory = _default_stage_path,
) -> ToolResult:
    root = roots.get(action.payload.root_id)
    if root is None:
        return _result(
            action,
            ToolStatus.DENIED,
            "UNTRUSTED_TARGET",
            "ROOT_UNREGISTERED",
            SideEffectState.NONE,
        )
    try:
        resolver = SecurePathResolver(root)
        resolved = resolver.resolve_for_write(Path(action.payload.relative_path))
        target_path = resolver.root.joinpath(*resolved._canonical_relative_parent, resolved.basename)
        source = target_path.read_bytes()
    except (OSError, PathSecurityError, UnicodeError):
        return _result(action, ToolStatus.DENIED, "UNTRUSTED_TARGET", "TARGET_UNSAFE", SideEffectState.NONE)
    if hashlib.sha256(source).hexdigest() != action.payload.base_sha256:
        return _result(
            action,
            ToolStatus.FAILED,
            "STALE_BASELINE",
            "BASE_SHA256_MISMATCH",
            SideEffectState.NONE,
        )
    try:
        replacement = _apply(source, action)
    except UnicodeError:
        replacement = None
    if replacement is None:
        return _result(
            action,
            ToolStatus.FAILED,
            "PATCH_CONTEXT_MISMATCH",
            "EXPECTED_TEXT_MISMATCH",
            SideEffectState.NONE,
        )
    staged = stage_path_factory(target_path)
    try:
        if staged.parent != target_path.parent or staged.name == target_path.name:
            return _result(action, ToolStatus.DENIED, "UNTRUSTED_TARGET", "STAGE_PATH_UNSAFE", SideEffectState.NONE)
        descriptor = os.open(
            staged,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(replacement)
            output.flush()
            os.fsync(output.fileno())
        current = resolver.resolve_for_write(Path(action.payload.relative_path))
        current_path = resolver.root.joinpath(*current._canonical_relative_parent, current.basename)
        if current != resolved or current_path != target_path:
            return _result(action, ToolStatus.FAILED, "STALE_BASELINE", "TARGET_CHANGED", SideEffectState.NONE)
        if hashlib.sha256(target_path.read_bytes()).hexdigest() != action.payload.base_sha256:
            return _result(action, ToolStatus.FAILED, "STALE_BASELINE", "TARGET_CHANGED", SideEffectState.NONE)
        os.replace(staged, target_path)
        _fsync_parent(target_path.parent)
        return _result(action, ToolStatus.SUCCEEDED, "PATCH", "PATCH_APPLIED", SideEffectState.APPLIED)
    except (OSError, PathSecurityError):
        return _result(
            action,
            ToolStatus.FAILED,
            "PATCH_FAILED",
            "STAGED_REPLACEMENT_FAILED",
            SideEffectState.NONE,
        )
    finally:
        staged.unlink(missing_ok=True)


__all__ = ["apply_action"]

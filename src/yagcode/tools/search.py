"""Literal-only, explicitly bounded trusted search."""

from __future__ import annotations

from collections.abc import Mapping
from fnmatch import fnmatch
from pathlib import Path

from yagcode.domain.actions import SearchLiteralAction
from yagcode.domain.results import SideEffectState, ToolResult, ToolStatus


def _denied(action: SearchLiteralAction, reason: str) -> ToolResult:
    return ToolResult(
        action_id=action.action_id,
        status=ToolStatus.DENIED,
        category="SEARCH",
        reason_code=reason,
        side_effect_state=SideEffectState.NONE,
        retryable=False,
    )


def _resolve_root(root: Path, relative_path: str) -> Path:
    if Path(relative_path).is_absolute():
        raise ValueError("SEARCH_PATH_UNTRUSTED")
    relative = Path(relative_path)
    if any(part in {".", ".."} for part in relative.parts):
        raise ValueError("SEARCH_PATH_UNTRUSTED")
    trusted_root = root.resolve(strict=True)
    target = (trusted_root / relative).resolve(strict=False)
    if not target.is_relative_to(trusted_root) or target.is_symlink() or not target.is_dir():
        raise ValueError("SEARCH_PATH_UNTRUSTED")
    return target


def search_action(action: SearchLiteralAction, *, roots: Mapping[str, Path]) -> ToolResult:
    root = roots.get(action.payload.root_id)
    if root is None:
        return _denied(action, "ROOT_UNREGISTERED")
    try:
        search_root = _resolve_root(root, action.payload.relative_path)
    except (OSError, ValueError):
        return _denied(action, "SEARCH_PATH_UNTRUSTED")
    hits: list[str] = []
    globs = action.payload.globs or ("*",)
    try:
        for path in sorted(search_root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root.resolve(strict=True)).as_posix()
            if not any(fnmatch(path.name, pattern) or fnmatch(relative, pattern) for pattern in globs):
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if action.payload.query in line:
                    hits.append(f"match:{relative}:{line_number}")
                    if len(hits) >= action.payload.max_results:
                        return ToolResult(
                            action_id=action.action_id,
                            status=ToolStatus.SUCCEEDED,
                            category="SEARCH",
                            reason_code="SEARCH_TRUNCATED",
                            artifact_refs=hits,
                            side_effect_state=SideEffectState.NONE,
                            retryable=True,
                        )
    except (OSError, UnicodeError):
        return _denied(action, "SEARCH_READ_FAILED")
    return ToolResult(
        action_id=action.action_id,
        status=ToolStatus.SUCCEEDED,
        category="SEARCH",
        reason_code="SEARCH_OK",
        artifact_refs=hits,
        side_effect_state=SideEffectState.NONE,
        retryable=True,
    )


__all__ = ["search_action"]

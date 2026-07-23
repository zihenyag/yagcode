"""Bounded trusted file reads returning content-addressed metadata."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from yagcode.domain.actions import ReadTextAction
from yagcode.domain.results import SideEffectState, ToolResult, ToolStatus


@dataclass(frozen=True, slots=True)
class FileRead:
    content: bytes
    sha256: str
    truncated: bool


def _denied(action: ReadTextAction, reason: str) -> ToolResult:
    return ToolResult(
        action_id=action.action_id,
        status=ToolStatus.DENIED,
        category="READ",
        reason_code=reason,
        side_effect_state=SideEffectState.NONE,
        retryable=False,
    )


def _resolve_trusted_file(root: Path, relative_path: str) -> Path:
    if relative_path == "" or Path(relative_path).is_absolute():
        raise ValueError("TOOL_PATH_UNTRUSTED")
    relative = Path(relative_path)
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("TOOL_PATH_UNTRUSTED")
    trusted_root = root.resolve(strict=True)
    target = (trusted_root / relative).resolve(strict=False)
    if not target.is_relative_to(trusted_root):
        raise ValueError("TOOL_PATH_UNTRUSTED")
    if target.is_symlink() or not target.is_file():
        raise ValueError("TOOL_PATH_UNTRUSTED")
    return target


def read_bounded(path: Path, max_bytes: int) -> FileRead:
    with path.open("rb") as stream:
        content = stream.read(max_bytes + 1)
    bounded = content[:max_bytes]
    return FileRead(bounded, hashlib.sha256(bounded).hexdigest(), len(content) > max_bytes)


def _read_text_range_bounded(path: Path, *, start_line: int, end_line: int, max_bytes: int) -> FileRead:
    buffer = bytearray()
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line_number > end_line:
                break
            if line_number < start_line:
                continue
            remaining = max_bytes + 1 - len(buffer)
            if remaining > 0:
                buffer.extend(line.encode("utf-8")[:remaining])
            if len(buffer) > max_bytes:
                break
    bounded = bytes(buffer[:max_bytes])
    return FileRead(bounded, hashlib.sha256(bounded).hexdigest(), len(buffer) > max_bytes)


def read_text_action(action: ReadTextAction, *, roots: Mapping[str, Path]) -> ToolResult:
    root = roots.get(action.payload.root_id)
    if root is None:
        return _denied(action, "ROOT_UNREGISTERED")
    try:
        target = _resolve_trusted_file(root, action.payload.relative_path)
    except (OSError, UnicodeError, ValueError):
        return _denied(action, "TARGET_UNSAFE")
    try:
        file_read = _read_text_range_bounded(
            target,
            start_line=action.payload.start_line,
            end_line=action.payload.end_line,
            max_bytes=action.payload.max_bytes,
        )
    except (OSError, UnicodeError):
        return _denied(action, "TARGET_UNSAFE")
    return ToolResult(
        action_id=action.action_id,
        status=ToolStatus.SUCCEEDED,
        category="READ_TRUNCATED" if file_read.truncated else "READ",
        reason_code="READ_TRUNCATED" if file_read.truncated else "READ_OK",
        artifact_refs=[
            f"sha256:{file_read.sha256}",
            f"bytes:{len(file_read.content)}",
            f"truncated:{str(file_read.truncated).lower()}",
        ],
        side_effect_state=SideEffectState.NONE,
        retryable=True,
    )


__all__ = ["FileRead", "read_bounded", "read_text_action"]

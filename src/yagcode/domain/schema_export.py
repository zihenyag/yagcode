"""Canonical Action JSON Schema export and strict check/check-or-write modes."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from yagcode.domain.actions import Action
from yagcode.domain.atomic_write import (
    DEFAULT_OPS as ATOMIC_DEFAULT_OPS,
    ExportOps,
    durable_atomic_write,
    last_residual_staging_path,
    read_target_no_follow,
    sync_parent_verified,
)


ExportMode = Literal["check", "check-or-write"]
REPOSITORY_ROOT = Path(__file__).parents[3]
DEFAULT_TARGET = REPOSITORY_ROOT / "contracts" / "action.schema.json"


def canonical_action_schema_bytes() -> bytes:
    raw_schema = TypeAdapter(Action).json_schema()
    return (json.dumps(raw_schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


DEFAULT_OPS = replace(ATOMIC_DEFAULT_OPS, serializer=canonical_action_schema_bytes)


def _failure(code: str) -> int:
    print(code, file=sys.stderr)
    return 2


def export_schema(target: Path, mode: ExportMode, ops: ExportOps, *, trusted_root: Path) -> int:
    try:
        payload = ops.serializer()
        if not isinstance(payload, bytes):
            return _failure("SCHEMA_SERIALIZER_INVALID")
    except Exception:
        return _failure("SCHEMA_SERIALIZER_FAILED")
    if mode == "check":
        try:
            existing = read_target_no_follow(target, ops, trusted_root=trusted_root)
        except Exception:
            return _failure("SCHEMA_READ_FAILED")
        if not existing.exists or existing.payload != payload:
            return 1
        if existing.parent_identity is None:
            return _failure("SCHEMA_PARENT_SYNC_UNCONFIRMED")
        try:
            sync_parent_verified(
                target.parent,
                ops,
                trusted_root=trusted_root,
                expected_identity=existing.parent_identity,
            )
        except Exception:
            return _failure("SCHEMA_PARENT_SYNC_UNCONFIRMED")
        return 0
    if mode != "check-or-write":
        return _failure("SCHEMA_MODE_INVALID")
    outcome = durable_atomic_write(target, payload, ops, trusted_root=trusted_root)
    if outcome in ("DURABLE", "UNCHANGED"):
        return 0
    if outcome == "SYNC_UNCONFIRMED":
        return _failure("SCHEMA_PARENT_SYNC_UNCONFIRMED")
    residual = last_residual_staging_path()
    if residual is not None:
        return _failure(f"SCHEMA_WRITE_FAILED_RESIDUAL={residual}")
    return _failure("SCHEMA_WRITE_FAILED")


def main(
    argv: Sequence[str] | None = None,
    *,
    target: Path = DEFAULT_TARGET,
    trusted_root: Path = REPOSITORY_ROOT,
    ops: ExportOps = DEFAULT_OPS,
) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="export_schemas")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--check-or-write", action="store_true")
    parsed = parser.parse_args(argv)
    mode: ExportMode = "check" if parsed.check else "check-or-write"
    return export_schema(target, mode, ops, trusted_root=trusted_root)


__all__ = ["DEFAULT_OPS", "DEFAULT_TARGET", "REPOSITORY_ROOT", "canonical_action_schema_bytes", "export_schema", "main"]

"""Export public sidecar API schemas and golden fixtures."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from dataclasses import replace

from pathlib import Path
from typing import Sequence

from yagcode.domain.atomic_write import ExportOps, FileIdentity, LstatSnapshot, StagedFile
from yagcode.domain.schema_export import DEFAULT_OPS, export_schema
from yagcode.api.schemas import EVENT_ADAPTER, PUBLIC_VIEW_ADAPTER, event_fixture, review_fixture


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET_DIR = REPOSITORY_ROOT / "contracts" / "api"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _schema_with_dialect(schema: dict[str, object]) -> dict[str, object]:
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}


def artifacts() -> dict[Path, bytes]:
    return {
        Path("public-views.schema.json"): _canonical(
            _schema_with_dialect(PUBLIC_VIEW_ADAPTER.json_schema())
        ),
        Path("events.schema.json"): _canonical(_schema_with_dialect(EVENT_ADAPTER.json_schema())),
        Path("fixtures/review-view.json"): review_fixture().model_dump_json(
            indent=2, by_alias=False
        ).encode("utf-8")
        + b"\n",
        Path("fixtures/run-state-event.json"): event_fixture().model_dump_json(
            indent=2, by_alias=False
        ).encode("utf-8")
        + b"\n",
    }


def _windows_reparse(info: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(info, "st_file_attributes", 0) & reparse_flag)


def _windows_identity(info: os.stat_result) -> FileIdentity:
    if _windows_reparse(info):
        raise OSError("Windows reparse point rejected")
    if stat.S_ISREG(info.st_mode) and getattr(info, "st_nlink", 1) != 1:
        raise OSError("Windows hardlink target rejected")
    return FileIdentity(
        "windows",
        (
            int(info.st_dev),
            int(info.st_ino),
            int(getattr(info, "st_file_attributes", 0)),
            int(getattr(info, "st_reparse_tag", 0)),
            int(getattr(info, "st_nlink", 1)),
        ),
    )


def _windows_lstat(path: Path) -> LstatSnapshot:
    info = os.stat(path, follow_symlinks=False)
    return LstatSnapshot(info.st_mode, _windows_identity(info))


class _WindowsReadHandle:
    def __init__(self, path: Path) -> None:
        self._file = path.open("rb")

    def read(self) -> bytes:
        return self._file.read()

    def fstat_identity(self) -> FileIdentity:
        return _windows_identity(os.fstat(self._file.fileno()))

    def close(self) -> None:
        self._file.close()


class _WindowsTempHandle:
    def __init__(self, descriptor: int) -> None:
        self._file = os.fdopen(descriptor, "wb")

    def write(self, data: bytes) -> int:
        return self._file.write(data)

    def flush(self) -> None:
        self._file.flush()

    def fileno(self) -> int:
        return self._file.fileno()

    def close(self) -> None:
        self._file.close()


class _WindowsDirectorySyncHandle:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._identity = _windows_lstat(path).identity

    def fstat_identity(self) -> FileIdentity:
        return self._identity

    def sync_entry(self) -> None:
        if _windows_lstat(self._path).identity != self._identity:
            raise OSError("Windows parent identity changed")

    def close(self) -> None:
        return None


def _windows_temp_factory(parent: Path) -> StagedFile:
    descriptor, temp_name = tempfile.mkstemp(prefix=".schema-", dir=parent)
    return StagedFile(Path(temp_name), _WindowsTempHandle(descriptor))


def _artifact_ops(payload: bytes) -> ExportOps:
    def serializer() -> bytes:
        return payload

    if os.name != "nt":
        return replace(DEFAULT_OPS, serializer=serializer)
    return replace(
        DEFAULT_OPS,
        serializer=serializer,
        lstat=_windows_lstat,
        open_read_no_follow=_WindowsReadHandle,
        mkdir=lambda path: path.mkdir(parents=True, exist_ok=True),
        temp_factory=_windows_temp_factory,
        fsync=os.fsync,
        replace=os.replace,
        open_parent_no_follow=_WindowsDirectorySyncHandle,
        cleanup=lambda path: path.unlink(missing_ok=True),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="export_api_schemas")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--check-or-write", action="store_true")
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET_DIR)
    parsed = parser.parse_args(argv)
    target_dir = parsed.target_dir
    expected = artifacts()
    mode = "check" if parsed.check else "check-or-write"
    for relative, payload in expected.items():
        result = export_schema(
            target_dir / relative,
            mode,
            _artifact_ops(payload),
            trusted_root=target_dir,
        )
        if result != 0:
            return result
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

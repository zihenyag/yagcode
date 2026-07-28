"""contract tests; test-owned oracles deliberately do not import production."""
# ruff: noqa: E701, E702

from __future__ import annotations

import copy
import importlib
import json
import os
import stat
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol

import pytest


ExportMode = Literal["check", "check-or-write"]
SEMANTICS_FIXTURE = Path(__file__).parents[2] / "fixtures/contracts/action_schema_semantics.json"


@dataclass(frozen=True)
class FileIdentity:
    platform: Literal["posix", "windows"]
    token: tuple[int, ...]


@dataclass(frozen=True)
class LstatSnapshot:
    mode: int
    identity: FileIdentity


class BinaryReadHandle(Protocol):
    def read(self) -> bytes: ...
    def fstat_identity(self) -> FileIdentity: ...
    def close(self) -> None: ...


class BinaryTempHandle(Protocol):
    def write(self, data: bytes) -> int: ...
    def flush(self) -> None: ...
    def fileno(self) -> int: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class StagedFile:
    path: Path
    handle: BinaryTempHandle


class DirectorySyncHandle(Protocol):
    def fstat_identity(self) -> FileIdentity: ...
    def sync_entry(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class ExportOps:
    serializer: Callable[[], bytes]
    lstat: Callable[[Path], LstatSnapshot]
    open_read_no_follow: Callable[[Path], BinaryReadHandle]
    mkdir: Callable[[Path], None]
    temp_factory: Callable[[Path], StagedFile]
    fsync: Callable[[int], None]
    replace: Callable[[Path, Path], None]
    open_parent_no_follow: Callable[[Path], DirectorySyncHandle]
    cleanup: Callable[[Path], None]


def load_schema_export_contract() -> tuple[Any, Any, Any]:
    """Import production only at execution time so RED remains a valid collection."""

    try:
        atomic = importlib.import_module("yagcode.domain.atomic_write")
        schema = importlib.import_module("yagcode.domain.schema_export")
        cli = importlib.import_module("scripts.export_schemas")
    except (ImportError, ModuleNotFoundError) as error:
        pytest.fail(f"PRODUCTION_CONTRACT_MISSING: {error}")
    return atomic, schema, cli


def test_owned_canonical_schema_bytes(raw: object) -> bytes:
    return (json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


test_owned_canonical_schema_bytes.__test__ = False


def _resolve(raw: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    if "$ref" not in value:
        return value
    return raw["$defs"][value["$ref"].rsplit("/", 1)[-1]]


def _constraint(value: dict[str, Any]) -> dict[str, Any]:
    keys = ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "pattern", "enum", "maxProperties")
    result = {key: value[key] for key in keys if key in value}
    for key in ("items", "propertyNames", "additionalProperties"):
        if key in value and isinstance(value[key], dict):
            nested = _constraint(value[key])
            if nested:
                result[key] = nested
    return result


def test_owned_project_schema_semantics(raw_schema: dict[str, Any]) -> dict[str, Any]:
    """Return a layout-independent projection of all SPEC-defined schema semantics."""

    mapping = raw_schema.get("discriminator", {}).get("mapping", {})
    if set(mapping) != {
        "list_directory", "read_text", "search_literal", "apply_patch",
        "git_inspect", "run_command", "run_validation", "request_review",
    }:
        raise AssertionError("eight action branches are required")
    defs = raw_schema.get("$defs", {})
    objects: dict[str, dict[str, Any]] = {}
    for name, value in defs.items():
        if value.get("type") != "object":
            continue
        properties = value.get("properties", {})
        objects[name] = {
            "required": value.get("required"),
            "closed": value.get("additionalProperties") is False,
            "properties": {key: _constraint(_resolve(raw_schema, prop)) for key, prop in properties.items()},
        }
    branches: dict[str, dict[str, str]] = {}
    for kind, ref in mapping.items():
        action_name = ref.rsplit("/", 1)[-1]
        action = defs[action_name]
        payload_name = action["properties"]["payload"]["$ref"].rsplit("/", 1)[-1]
        branches[kind] = {"action": action_name, "payload": payload_name}
    return {"branches": branches, "objects": objects}


test_owned_project_schema_semantics.__test__ = False


def _semantic_assertion(raw_schema: dict[str, Any], expected: dict[str, Any]) -> None:
    projection = test_owned_project_schema_semantics(raw_schema)
    assert projection["branches"] == expected["branches"]
    all_objects = projection["objects"]
    for name, expected_object in expected["objects"].items():
        if name == "Action":
            for branch in expected["branches"].values():
                actual = all_objects[branch["action"]]
                assert actual["required"] == expected_object["required"]
                assert actual["closed"] is expected_object["closed"]
            continue
        actual = all_objects[name]
        assert actual["required"] == expected_object["required"]
        assert actual["closed"] is expected_object["closed"]
    constraints = expected["constraints"]
    props = all_objects
    lookup = {
        "action_id": ("ListDirectoryAction", "action_id"), "run_id": ("ListDirectoryAction", "run_id"),
        "generation": ("ListDirectoryAction", "generation"), "reason_summary": ("ListDirectoryAction", "reason_summary"),
        "root_id": ("ListDirectoryPayload", "root_id"), "optional_path": ("ListDirectoryPayload", "relative_path"),
        "required_path": ("ReadTextPayload", "relative_path"), "short_text": ("RunCommandPayload", "template_id"),
        "hunk_text": ("PatchHunk", "expected_text"), "list_directory.max_depth": ("ListDirectoryPayload", "max_depth"),
        "list_directory.max_entries": ("ListDirectoryPayload", "max_entries"), "read_text.start_line": ("ReadTextPayload", "start_line"),
        "read_text.end_line": ("ReadTextPayload", "end_line"), "read_text.max_bytes": ("ReadTextPayload", "max_bytes"),
        "search_literal.query": ("SearchLiteralPayload", "query"), "search_literal.globs": ("SearchLiteralPayload", "globs"),
        "search_literal.max_results": ("SearchLiteralPayload", "max_results"), "apply_patch.base_sha256": ("ApplyPatchPayload", "base_sha256"),
        "apply_patch.hunks": ("ApplyPatchPayload", "hunks"), "patch_hunk.start_line": ("PatchHunk", "start_line"),
        "patch_hunk.delete_line_count": ("PatchHunk", "delete_line_count"), "git_inspect.operation": ("GitInspectPayload", "operation"),
        "run_command.arguments": ("RunCommandPayload", "arguments"), "run_command.timeout_ms": ("RunCommandPayload", "timeout_ms"),
        "run_validation.target_paths": ("RunValidationPayload", "target_paths"), "request_review.summary": ("RequestReviewPayload", "summary"),
        "request_review.uncovered": ("RequestReviewPayload", "uncovered"),
    }
    for key, required in constraints.items():
        definition, property_name = lookup[key]
        assert props[definition]["properties"][property_name] == required


def _test_owned_raw_schema(expected: dict[str, Any]) -> dict[str, Any]:
    """Handwritten-layout test schema, deliberately independent of Action/Pydantic."""

    branch_defs: dict[str, dict[str, Any]] = {}
    common = {
        "action_id": expected["constraints"]["action_id"],
        "run_id": expected["constraints"]["run_id"],
        "generation": expected["constraints"]["generation"],
        "reason_summary": expected["constraints"]["reason_summary"],
    }
    for kind, names in expected["branches"].items():
        branch_defs[names["action"]] = {
            "type": "object", "additionalProperties": False,
            "required": expected["objects"]["Action"]["required"],
            "properties": {**copy.deepcopy(common), "kind": {"const": kind}, "payload": {"$ref": f"#/$defs/{names['payload']}"}},
        }
    for name, definition in expected["objects"].items():
        if name == "Action":
            continue
        branch_defs[name] = {"type": "object", "additionalProperties": not definition["closed"], "required": definition["required"], "properties": {field: {} for field in definition["required"]}}
    lookup = {
        "root_id": ("ListDirectoryPayload", "root_id"), "optional_path": ("ListDirectoryPayload", "relative_path"),
        "required_path": ("ReadTextPayload", "relative_path"), "short_text": ("RunCommandPayload", "template_id"),
        "hunk_text": ("PatchHunk", "expected_text"), "list_directory.max_depth": ("ListDirectoryPayload", "max_depth"),
        "list_directory.max_entries": ("ListDirectoryPayload", "max_entries"), "read_text.start_line": ("ReadTextPayload", "start_line"),
        "read_text.end_line": ("ReadTextPayload", "end_line"), "read_text.max_bytes": ("ReadTextPayload", "max_bytes"),
        "search_literal.query": ("SearchLiteralPayload", "query"), "search_literal.globs": ("SearchLiteralPayload", "globs"),
        "search_literal.max_results": ("SearchLiteralPayload", "max_results"), "apply_patch.base_sha256": ("ApplyPatchPayload", "base_sha256"),
        "apply_patch.hunks": ("ApplyPatchPayload", "hunks"), "patch_hunk.start_line": ("PatchHunk", "start_line"),
        "patch_hunk.delete_line_count": ("PatchHunk", "delete_line_count"), "git_inspect.operation": ("GitInspectPayload", "operation"),
        "run_command.arguments": ("RunCommandPayload", "arguments"), "run_command.timeout_ms": ("RunCommandPayload", "timeout_ms"),
        "run_validation.target_paths": ("RunValidationPayload", "target_paths"), "request_review.summary": ("RequestReviewPayload", "summary"),
        "request_review.uncovered": ("RequestReviewPayload", "uncovered"),
    }
    for key, (definition, field) in lookup.items():
        branch_defs[definition]["properties"][field] = copy.deepcopy(expected["constraints"][key])
    mapping = {kind: f"#/$defs/{names['action']}" for kind, names in expected["branches"].items()}
    return {"$defs": branch_defs, "discriminator": {"propertyName": "kind", "mapping": mapping}}


def _constraint_leaf_paths(value: dict[str, Any], prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    leaves: list[tuple[str, ...]] = []
    for key, nested in value.items():
        if isinstance(nested, dict):
            leaves.extend(_constraint_leaf_paths(nested, (*prefix, key)))
        else:
            leaves.append((*prefix, key))
    return leaves


def test_owned_semantic_fixture_and_exhaustive_mutation_oracle() -> None:
    expected = json.loads(SEMANTICS_FIXTURE.read_text())
    raw = _test_owned_raw_schema(expected)
    _semantic_assertion(raw, expected)
    with pytest.raises(AssertionError):
        _semantic_assertion({}, expected)
    for branch in expected["branches"]:
        mutated = copy.deepcopy(raw)
        mutated["discriminator"]["mapping"].pop(branch)
        with pytest.raises(AssertionError):
            _semantic_assertion(mutated, expected)
    for name, definition in expected["objects"].items():
        targets = list(expected["branches"].values()) if name == "Action" else [{"action": name}]
        for target in targets:
            actual_name = target["action"]
            for required in definition["required"]:
                mutated = copy.deepcopy(raw)
                mutated["$defs"][actual_name]["required"].remove(required)
                with pytest.raises(AssertionError):
                    _semantic_assertion(mutated, expected)
            mutated = copy.deepcopy(raw)
            mutated["$defs"][actual_name]["additionalProperties"] = True
            with pytest.raises(AssertionError):
                _semantic_assertion(mutated, expected)
    lookup = {
        "action_id": ("ListDirectoryAction", "action_id"), "run_id": ("ListDirectoryAction", "run_id"),
        "generation": ("ListDirectoryAction", "generation"), "reason_summary": ("ListDirectoryAction", "reason_summary"),
        "root_id": ("ListDirectoryPayload", "root_id"), "optional_path": ("ListDirectoryPayload", "relative_path"),
        "required_path": ("ReadTextPayload", "relative_path"), "short_text": ("RunCommandPayload", "template_id"),
        "hunk_text": ("PatchHunk", "expected_text"), "list_directory.max_depth": ("ListDirectoryPayload", "max_depth"),
        "list_directory.max_entries": ("ListDirectoryPayload", "max_entries"), "read_text.start_line": ("ReadTextPayload", "start_line"),
        "read_text.end_line": ("ReadTextPayload", "end_line"), "read_text.max_bytes": ("ReadTextPayload", "max_bytes"),
        "search_literal.query": ("SearchLiteralPayload", "query"), "search_literal.globs": ("SearchLiteralPayload", "globs"),
        "search_literal.max_results": ("SearchLiteralPayload", "max_results"), "apply_patch.base_sha256": ("ApplyPatchPayload", "base_sha256"),
        "apply_patch.hunks": ("ApplyPatchPayload", "hunks"), "patch_hunk.start_line": ("PatchHunk", "start_line"),
        "patch_hunk.delete_line_count": ("PatchHunk", "delete_line_count"), "git_inspect.operation": ("GitInspectPayload", "operation"),
        "run_command.arguments": ("RunCommandPayload", "arguments"), "run_command.timeout_ms": ("RunCommandPayload", "timeout_ms"),
        "run_validation.target_paths": ("RunValidationPayload", "target_paths"), "request_review.summary": ("RequestReviewPayload", "summary"),
        "request_review.uncovered": ("RequestReviewPayload", "uncovered"),
    }
    for key, constraint in expected["constraints"].items():
        for leaf in _constraint_leaf_paths(constraint):
            mutated = copy.deepcopy(raw)
            value = mutated["$defs"][lookup[key][0]]["properties"][lookup[key][1]]
            for part in leaf[:-1]:
                value = value[part]
            value.pop(leaf[-1])
            with pytest.raises(AssertionError):
                _semantic_assertion(mutated, expected)


def test_runtime_action_schema_matches_independent_semantics_fixture() -> None:
    expected = json.loads(SEMANTICS_FIXTURE.read_text())
    from pydantic import TypeAdapter
    from yagcode.domain.actions import Action

    _semantic_assertion(TypeAdapter(Action).json_schema(), expected)


def test_owned_canonical_encoding_and_mutations() -> None:
    raw = {"z": "雪", "a": [2, 1]}
    expected = b'{\n  "a": [\n    2,\n    1\n  ],\n  "z": "' + "雪".encode("utf-8") + b'"\n}\n'
    assert test_owned_canonical_schema_bytes(raw) == expected
    alternatives = (
        json.dumps(raw, ensure_ascii=True, indent=2, sort_keys=True).encode(),
        (json.dumps(raw, ensure_ascii=False, indent=2) + "\n").encode(),
        (json.dumps(raw, ensure_ascii=False, indent=4, sort_keys=True) + "\n").encode(),
        json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True).encode(),
    )
    assert all(candidate != expected for candidate in alternatives)


def _schema_bytes() -> bytes:
    from pydantic import TypeAdapter
    from yagcode.domain.actions import Action

    return test_owned_canonical_schema_bytes(TypeAdapter(Action).json_schema())


def _default_ops(schema: Any) -> Any:
    return schema.DEFAULT_OPS


def _assert_same_mtime(path: Path, before: int) -> None:
    assert path.stat().st_mtime_ns == before


@pytest.mark.posix_only
def test_posix_regular_identity_includes_change_metadata(tmp_path: Path) -> None:
    atomic, _, _ = load_schema_export_contract()
    target = tmp_path / "target.txt"
    target.write_bytes(b"old")
    original = atomic.DEFAULT_OPS.lstat(target).identity
    target.unlink()
    target.write_bytes(b"replacement")
    replacement = atomic.DEFAULT_OPS.lstat(target).identity
    assert original != replacement
    assert len(original.token) == 5


def test_check_missing_and_stale_are_nonzero_without_writing(tmp_path: Path) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "contracts" / "action.schema.json"
    assert schema.export_schema(target, "check", _default_ops(schema), trusted_root=tmp_path) == 1
    assert not target.exists()
    target.parent.mkdir()
    target.write_bytes(b"stale")
    before = target.stat().st_mtime_ns
    result = schema.export_schema(target, "check", _default_ops(schema), trusted_root=tmp_path)
    assert result == 1
    assert target.read_bytes() == b"stale"
    _assert_same_mtime(target, before)


@pytest.mark.parametrize("mode", ["check", "check-or-write"])
def test_equal_reconciles_parent_without_staging(tmp_path: Path, mode: ExportMode) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "contracts" / "action.schema.json"
    target.parent.mkdir()
    target.write_bytes(_schema_bytes())
    before = target.stat().st_mtime_ns
    ops = _default_ops(schema)
    calls = {"mkdir": 0, "temp": 0, "replace": 0, "cleanup": 0}
    for name in calls:
        original = getattr(ops, {"temp": "temp_factory"}.get(name, name))
        calls[name] = 0
        def counted(*args: Any, _original: Any = original, _name: str = name, **kwargs: Any) -> Any:
            calls[_name] += 1
            return _original(*args, **kwargs)
        ops = replace(ops, **{{"temp": "temp_factory"}.get(name, name): counted})
    assert schema.export_schema(target, mode, ops, trusted_root=tmp_path) == 0
    assert calls == {"mkdir": 0, "temp": 0, "replace": 0, "cleanup": 0}
    _assert_same_mtime(target, before)


@pytest.mark.parametrize("mode", ["check", "check-or-write"])
def test_equal_parent_replacement_after_read_is_rejected(tmp_path: Path, mode: ExportMode) -> None:
    """The parent captured during the target read, not a later self-consistent one, is authoritative."""

    atomic, schema, _ = load_schema_export_contract()
    del atomic
    parent = tmp_path / "parent"
    replacement = tmp_path / "replacement"
    parent.mkdir()
    replacement.mkdir()
    target = parent / "action.schema.json"
    target.write_bytes(_schema_bytes())
    (replacement / "action.schema.json").write_bytes(_schema_bytes())
    ops = _default_ops(schema)
    original_open = ops.open_read_no_follow
    swapped = False
    class ReadThenSwap:
        def __init__(self, handle: Any) -> None:
            self.handle = handle
        def read(self) -> bytes: return self.handle.read()
        def fstat_identity(self) -> Any: return self.handle.fstat_identity()
        def close(self) -> None:
            nonlocal swapped
            self.handle.close()
            if not swapped:
                swapped = True
                parent.rename(tmp_path / "former-parent")
                replacement.rename(parent)
    ops = replace(ops, open_read_no_follow=lambda path: ReadThenSwap(original_open(path)))
    assert schema.export_schema(target, mode, ops, trusted_root=tmp_path) == 2
    assert swapped is True


def test_serializer_non_bytes_is_a_stable_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    ops = replace(_default_ops(schema), serializer=lambda: "not-bytes")
    assert schema.export_schema(tmp_path / "action.schema.json", "check", ops, trusted_root=tmp_path) == 2
    assert capsys.readouterr().err.strip() == "SCHEMA_SERIALIZER_INVALID"


def test_direct_unsupported_mode_is_stable_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    assert schema.export_schema(tmp_path / "action.schema.json", "unsupported", _default_ops(schema), trusted_root=tmp_path) == 2  # type: ignore[arg-type]
    assert capsys.readouterr().err.strip() == "SCHEMA_MODE_INVALID"


def test_check_or_write_atomically_writes_and_second_run_preserves_mtime(tmp_path: Path) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "contracts" / "action.schema.json"
    assert schema.export_schema(target, "check-or-write", _default_ops(schema), trusted_root=tmp_path) == 0
    assert target.read_bytes() == _schema_bytes()
    before = target.stat().st_mtime_ns
    assert schema.export_schema(target, "check-or-write", _default_ops(schema), trusted_root=tmp_path) == 0
    _assert_same_mtime(target, before)


@pytest.mark.parametrize("bad_mode", [stat.S_IFLNK, stat.S_IFIFO])
def test_target_lstat_non_regular_is_rejected(tmp_path: Path, bad_mode: int) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"
    target.write_bytes(b"old")
    ops = replace(_default_ops(schema), lstat=lambda _: LstatSnapshot(bad_mode, FileIdentity("posix", (1, 2))))
    assert schema.export_schema(target, "check-or-write", ops, trusted_root=tmp_path) == 2
    assert target.read_bytes() == b"old"


def test_real_directory_target_is_rejected_without_mutation(tmp_path: Path) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"
    target.mkdir()
    assert schema.export_schema(target, "check-or-write", _default_ops(schema), trusted_root=tmp_path) == 2
    assert target.is_dir()
    assert list(target.iterdir()) == []


def test_rejects_target_and_parent_symlink_and_untrusted_target(tmp_path: Path) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    referent = tmp_path / "referent"
    referent.write_bytes(b"old")
    target = tmp_path / "linked.schema.json"
    try:
        target.symlink_to(referent)
    except OSError:
        pytest.skip("symlink unavailable on this platform")
    assert schema.export_schema(target, "check-or-write", _default_ops(schema), trusted_root=tmp_path) == 2
    assert referent.read_bytes() == b"old"
    parent_referent = tmp_path / "parent-referent"
    parent_referent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(parent_referent, target_is_directory=True)
    assert schema.export_schema(
        linked_parent / "action.schema.json",
        "check-or-write",
        _default_ops(schema),
        trusted_root=tmp_path,
    ) == 2
    assert not (parent_referent / "action.schema.json").exists()
    assert schema.export_schema(tmp_path.parent / "outside.json", "check", _default_ops(schema), trusted_root=tmp_path) == 2


def test_pre_replace_identity_change_refuses_to_replace(tmp_path: Path) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"
    target.write_bytes(b"old")
    ops = _default_ops(schema)
    original_factory = ops.temp_factory
    changed = False
    class CloseThenRace:
        def __init__(self, handle: Any) -> None:
            self.handle = handle
        def write(self, data: bytes) -> int: return self.handle.write(data)
        def flush(self) -> None: self.handle.flush()
        def fileno(self) -> int: return self.handle.fileno()
        def close(self) -> None:
            nonlocal changed
            self.handle.close()
            if not changed:
                changed = True
                target.unlink()
                target.write_bytes(b"racer")
    def factory(parent: Path) -> Any:
        staged = original_factory(parent)
        return type(staged)(staged.path, CloseThenRace(staged.handle))
    ops = replace(ops, temp_factory=factory)
    assert schema.export_schema(target, "check-or-write", ops, trusted_root=tmp_path) == 2
    assert changed is True
    assert target.read_bytes() == b"racer"


@pytest.mark.parametrize("hook", ["serializer", "lstat", "open_read_no_follow", "mkdir", "temp_factory", "fsync", "replace", "open_parent_no_follow", "cleanup"])
def test_fault_hooks_fail_closed_without_path_fallback(tmp_path: Path, hook: str) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"
    target.write_bytes(b"old")
    ops = _default_ops(schema)
    def boom(*_: Any, **__: Any) -> Any:
        raise RuntimeError(f"SENTINEL_{hook}")
    if hook == "serializer":
        ops = replace(ops, serializer=boom)
    else:
        ops = replace(ops, **{hook: boom})
    if hook == "cleanup":
        ops = replace(ops, fsync=boom)
    assert schema.export_schema(target, "check-or-write", ops, trusted_root=tmp_path) == 2
    if hook == "open_parent_no_follow":
        assert target.read_bytes() == _schema_bytes()
    else:
        assert target.read_bytes() == b"old"


@pytest.mark.parametrize("fault", ["fstat", "sync_entry", "close"])
def test_equal_parent_sync_faults_are_unconfirmed_without_rewrite(
    tmp_path: Path, fault: str, capsys: pytest.CaptureFixture[str]
) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"
    target.write_bytes(_schema_bytes())
    before = target.stat().st_mtime_ns
    ops = _default_ops(schema)
    original_open = ops.open_parent_no_follow
    class FaultyDirectory:
        def __init__(self, handle: Any) -> None:
            self.handle = handle
        def fstat_identity(self) -> Any:
            if fault == "fstat":
                raise RuntimeError("SENTINEL_PARENT_FSTAT")
            return self.handle.fstat_identity()
        def sync_entry(self) -> None:
            if fault == "sync_entry":
                raise RuntimeError("SENTINEL_PARENT_SYNC")
            self.handle.sync_entry()
        def close(self) -> None:
            if fault == "close":
                raise RuntimeError("SENTINEL_PARENT_CLOSE")
            self.handle.close()
    ops = replace(ops, open_parent_no_follow=lambda parent: FaultyDirectory(original_open(parent)))
    assert schema.export_schema(target, "check", ops, trusted_root=tmp_path) == 2
    assert "SCHEMA_PARENT_SYNC_UNCONFIRMED" in capsys.readouterr().err
    assert target.read_bytes() == _schema_bytes()
    _assert_same_mtime(target, before)


@pytest.mark.parametrize("fault", ["write", "short_write", "flush", "fileno", "fsync", "close"])
def test_staging_faults_cleanup_without_replacing_existing_target(tmp_path: Path, fault: str) -> None:
    atomic, schema, _ = load_schema_export_contract()
    target = tmp_path / "action.schema.json"
    target.write_bytes(b"old")
    ops = _default_ops(schema)
    original_factory = ops.temp_factory
    staged_paths: list[Path] = []
    replace_calls = 0
    class FaultyTemp:
        def __init__(self, handle: Any) -> None:
            self.handle = handle
        def write(self, data: bytes) -> int:
            if fault == "write":
                raise RuntimeError("SENTINEL_WRITE")
            if fault == "short_write":
                return len(data) - 1
            return self.handle.write(data)
        def flush(self) -> None:
            if fault == "flush":
                raise RuntimeError("SENTINEL_FLUSH")
            self.handle.flush()
        def fileno(self) -> int:
            if fault == "fileno":
                raise RuntimeError("SENTINEL_FILENO")
            return self.handle.fileno()
        def close(self) -> None:
            if fault == "close":
                raise RuntimeError("SENTINEL_CLOSE")
            self.handle.close()
    def factory(parent: Path) -> Any:
        staged = original_factory(parent)
        staged_paths.append(staged.path)
        return type(staged)(staged.path, FaultyTemp(staged.handle))

    def fsync(fd: int) -> None:
        if fault == "fsync":
            raise RuntimeError("SENTINEL_FSYNC")
        ops.fsync(fd)

    def forbidden_replace(source: Path, destination: Path) -> None:
        nonlocal replace_calls
        del source, destination
        replace_calls += 1

    fault_ops = replace(ops, temp_factory=factory, fsync=fsync, replace=forbidden_replace)
    assert schema.export_schema(target, "check-or-write", fault_ops, trusted_root=tmp_path) == 2
    assert replace_calls == 0
    assert staged_paths
    if fault == "close" and os.name == "nt":
        assert staged_paths[0].exists()
        assert atomic.last_residual_staging_path() == staged_paths[0]
    else:
        assert not staged_paths[0].exists()
    assert target.read_bytes() == b"old"


def test_invalid_staging_location_is_closed_and_cleaned(tmp_path: Path) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"
    target.write_bytes(b"old")
    ops = _default_ops(schema)
    original_factory = ops.temp_factory
    created: list[Path] = []
    other_parent = tmp_path / "other"
    other_parent.mkdir()
    def factory(parent: Path) -> Any:
        del parent
        staged = original_factory(other_parent)
        created.append(staged.path)
        return staged
    assert schema.export_schema(target, "check-or-write", replace(ops, temp_factory=factory), trusted_root=tmp_path) == 2
    assert target.read_bytes() == b"old"
    assert created and not created[0].exists()


def test_staging_equal_to_target_is_closed_without_deleting_target(tmp_path: Path) -> None:
    atomic, schema, _ = load_schema_export_contract()
    target = tmp_path / "action.schema.json"
    target.write_bytes(b"old")
    closed = 0

    class NeverWrittenHandle:
        def write(self, data: bytes) -> int:
            del data
            raise AssertionError("invalid staging must be rejected before write")

        def flush(self) -> None:
            raise AssertionError("invalid staging must be rejected before flush")

        def fileno(self) -> int:
            raise AssertionError("invalid staging must be rejected before fileno")

        def close(self) -> None:
            nonlocal closed
            closed += 1

    ops = replace(
        _default_ops(schema),
        temp_factory=lambda _: atomic.StagedFile(target, NeverWrittenHandle()),
    )
    assert schema.export_schema(target, "check-or-write", ops, trusted_root=tmp_path) == 2
    assert closed == 1
    assert target.read_bytes() == b"old"


def test_temp_factory_partial_failure_cleans_its_own_artifact(tmp_path: Path) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"
    target.write_bytes(b"old")
    partial = tmp_path / ".factory-partial"

    def failing_factory(parent: Path) -> Any:
        assert parent == tmp_path
        partial.write_bytes(b"partial")
        partial.unlink()
        raise RuntimeError("SENTINEL_FACTORY_PARTIAL")

    ops = replace(_default_ops(schema), temp_factory=failing_factory)
    assert schema.export_schema(target, "check-or-write", ops, trusted_root=tmp_path) == 2
    assert target.read_bytes() == b"old"
    assert not partial.exists()


def test_cleanup_failure_reports_exact_residual_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"
    target.write_bytes(b"old")
    ops = _default_ops(schema)
    created: list[Path] = []
    original_factory = ops.temp_factory
    def factory(parent: Path) -> Any:
        staged = original_factory(parent)
        created.append(staged.path)
        return staged
    cleanup_calls = 0
    def cleanup(path: Path) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        assert path == created[0]
        raise RuntimeError("SENTINEL_CLEANUP")
    ops = replace(ops, temp_factory=factory, fsync=lambda _: (_ for _ in ()).throw(RuntimeError("SENTINEL_FSYNC")), cleanup=cleanup)
    assert schema.export_schema(target, "check-or-write", ops, trusted_root=tmp_path) == 2
    assert cleanup_calls == 1
    assert capsys.readouterr().err.strip() == f"SCHEMA_WRITE_FAILED_RESIDUAL={created[0]}"
    assert target.read_bytes() == b"old"


def test_residual_staging_report_is_isolated_per_execution_context(tmp_path: Path) -> None:
    atomic, schema, _ = load_schema_export_contract()
    barrier = threading.Barrier(2)

    def fail_with_residual(name: str) -> tuple[Any, Path | None, Path]:
        root = tmp_path / name
        root.mkdir()
        target = root / "action.schema.json"
        target.write_bytes(b"old")
        ops = _default_ops(schema)
        staged_paths: list[Path] = []
        original_factory = ops.temp_factory

        def factory(parent: Path) -> Any:
            staged = original_factory(parent)
            staged_paths.append(staged.path)
            return staged

        def cleanup(path: Path) -> None:
            assert path == staged_paths[0]
            raise RuntimeError(f"SENTINEL_CLEANUP_{name}")

        failing_ops = replace(
            ops,
            temp_factory=factory,
            fsync=lambda _: (_ for _ in ()).throw(RuntimeError(f"SENTINEL_FSYNC_{name}")),
            cleanup=cleanup,
        )
        outcome = atomic.durable_atomic_write(target, b"new", failing_ops, trusted_root=root)
        barrier.wait()
        return outcome, atomic.last_residual_staging_path(), staged_paths[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(fail_with_residual, ("first", "second")))
    assert all(outcome == "FAILED" for outcome, _, _ in results)
    assert all(observed == expected for _, observed, expected in results)


def test_cli_requires_exactly_one_mode_and_dispatches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    atomic, schema, cli = load_schema_export_contract()
    del atomic, schema
    for argv in ([], ["--check", "--check-or-write"], ["--unknown"], ["--check", "extra"]):
        with pytest.raises(SystemExit) as error:
            cli.main(argv, target=tmp_path / "action.schema.json", trusted_root=tmp_path)
        assert error.value.code == 2
    assert cli.main(["--check-or-write"], target=tmp_path / "action.schema.json", trusted_root=tmp_path) == 0
    assert cli.main(["--check"], target=tmp_path / "action.schema.json", trusted_root=tmp_path) == 0


@pytest.mark.parametrize(("argv", "expected_mode", "code"), [
    (["--check"], "check", 0), (["--check"], "check", 1), (["--check"], "check", 2),
    (["--check-or-write"], "check-or-write", 0), (["--check-or-write"], "check-or-write", 1),
    (["--check-or-write"], "check-or-write", 2),
])
def test_cli_legal_modes_preserve_exporter_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str], expected_mode: ExportMode, code: int
) -> None:
    atomic, schema, cli = load_schema_export_contract()
    del atomic, cli
    observed: list[ExportMode] = []
    def fake_export(target: Path, mode: ExportMode, ops: Any, *, trusted_root: Path) -> int:
        del target, ops, trusted_root
        observed.append(mode)
        return code
    monkeypatch.setattr(schema, "export_schema", fake_export)
    assert schema.main(argv, target=tmp_path / "action.schema.json", trusted_root=tmp_path) == code
    assert observed == [expected_mode]


@pytest.mark.parametrize("fault", ["open", "fstat", "identity", "sync", "close"])
@pytest.mark.parametrize("mode", ["check", "check-or-write"])
def test_equal_parent_fault_matrix_has_no_mutation(
    tmp_path: Path, mode: ExportMode, fault: str, capsys: pytest.CaptureFixture[str]
) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"
    target.write_bytes(_schema_bytes())
    before = target.stat().st_mtime_ns
    ops = _default_ops(schema)
    calls = {name: 0 for name in ("mkdir", "temp", "replace", "cleanup")}
    for name in calls:
        attr = "temp_factory" if name == "temp" else name
        original = getattr(ops, attr)
        def count(*args: Any, _original: Any = original, _name: str = name, **kwargs: Any) -> Any:
            calls[_name] += 1
            return _original(*args, **kwargs)
        ops = replace(ops, **{attr: count})
    if fault == "open":
        ops = replace(ops, open_parent_no_follow=lambda _: (_ for _ in ()).throw(RuntimeError("S_OPEN")))
    else:
        original_parent = ops.open_parent_no_follow
        class ParentFault:
            def __init__(self, handle: Any) -> None: self.handle = handle
            def fstat_identity(self) -> Any:
                if fault == "fstat": raise RuntimeError("S_FSTAT")
                if fault == "identity": return FileIdentity("posix", (999, 999))
                return self.handle.fstat_identity()
            def sync_entry(self) -> None:
                if fault == "sync": raise RuntimeError("S_SYNC")
                self.handle.sync_entry()
            def close(self) -> None:
                if fault == "close": raise RuntimeError("S_CLOSE")
                self.handle.close()
        ops = replace(ops, open_parent_no_follow=lambda path: ParentFault(original_parent(path)))
    assert schema.export_schema(target, mode, ops, trusted_root=tmp_path) == 2
    assert capsys.readouterr().err.strip() == "SCHEMA_PARENT_SYNC_UNCONFIRMED"
    assert calls == {name: 0 for name in calls}
    assert target.read_bytes() == _schema_bytes()
    _assert_same_mtime(target, before)


@pytest.mark.parametrize("replacement", ["symlink", "regular"])
def test_lstat_open_swap_matrix_refuses_replacement(tmp_path: Path, replacement: str) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"
    target.write_bytes(b"old")
    referent = tmp_path / "referent"
    referent.write_bytes(b"referent")
    ops = _default_ops(schema)
    original_open = ops.open_read_no_follow
    swapped = False
    def swap_then_open(path: Path) -> Any:
        nonlocal swapped
        if not swapped:
            swapped = True
            target.unlink()
            if replacement == "symlink": target.symlink_to(referent)
            else: target.write_bytes(b"racer")
        return original_open(path)
    ops = replace(ops, open_read_no_follow=swap_then_open)
    assert schema.export_schema(target, "check-or-write", ops, trusted_root=tmp_path) == 2
    assert referent.read_bytes() == b"referent"
    if replacement == "regular": assert target.read_bytes() == b"racer"


@pytest.mark.parametrize("fault", ["open", "read", "fstat", "close", "lstat"])
def test_read_fault_matrix_stops_before_mutation(tmp_path: Path, fault: str) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"; target.write_bytes(b"old")
    ops = _default_ops(schema)
    mutation = {"mkdir": 0, "temp": 0, "replace": 0}
    for name in mutation:
        attr = "temp_factory" if name == "temp" else name; original = getattr(ops, attr)
        def count(*args: Any, _original: Any = original, _name: str = name, **kwargs: Any) -> Any: mutation[_name] += 1; return _original(*args, **kwargs)
        ops = replace(ops, **{attr: count})
    if fault == "lstat": ops = replace(ops, lstat=lambda _: (_ for _ in ()).throw(RuntimeError("S_LSTAT")))
    elif fault == "open": ops = replace(ops, open_read_no_follow=lambda _: (_ for _ in ()).throw(RuntimeError("S_OPEN")))
    else:
        original_open = ops.open_read_no_follow
        class ReadFault:
            def __init__(self, handle: Any) -> None: self.handle = handle
            def read(self) -> bytes:
                if fault == "read": raise RuntimeError("S_READ")
                return self.handle.read()
            def fstat_identity(self) -> Any:
                if fault == "fstat": raise RuntimeError("S_FSTAT")
                return self.handle.fstat_identity()
            def close(self) -> None:
                if fault == "close": raise RuntimeError("S_CLOSE")
                self.handle.close()
        ops = replace(ops, open_read_no_follow=lambda path: ReadFault(original_open(path)))
    assert schema.export_schema(target, "check-or-write", ops, trusted_root=tmp_path) == 2
    assert mutation == {name: 0 for name in mutation}
    assert target.read_bytes() == b"old"


@pytest.mark.parametrize("fault", ["open", "fstat", "identity", "sync", "close"])
def test_post_replace_sync_fault_reconciles_on_later_equal_check(
    tmp_path: Path, fault: str, capsys: pytest.CaptureFixture[str]
) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"; target.write_bytes(b"old")
    ops = _default_ops(schema); original_open = ops.open_parent_no_follow
    class FaultParent:
        def __init__(self, handle: Any) -> None: self.handle = handle
        def fstat_identity(self) -> Any:
            if fault == "fstat": raise RuntimeError("POST_FSTAT")
            if fault == "identity": return FileIdentity("posix", (8, 8))
            return self.handle.fstat_identity()
        def sync_entry(self) -> None:
            if fault == "sync": raise RuntimeError("POST_SYNC")
            self.handle.sync_entry()
        def close(self) -> None:
            if fault == "close": raise RuntimeError("POST_CLOSE")
            self.handle.close()
    if fault == "open": ops = replace(ops, open_parent_no_follow=lambda _: (_ for _ in ()).throw(RuntimeError("POST_OPEN")))
    else: ops = replace(ops, open_parent_no_follow=lambda path: FaultParent(original_open(path)))
    assert schema.export_schema(target, "check-or-write", ops, trusted_root=tmp_path) == 2
    assert capsys.readouterr().err.strip() == "SCHEMA_PARENT_SYNC_UNCONFIRMED"
    assert target.read_bytes() == _schema_bytes()
    assert schema.export_schema(target, "check", _default_ops(schema), trusted_root=tmp_path) == 0
    before = target.stat().st_mtime_ns
    calls = {"temp": 0, "replace": 0}
    def count_temp(*args: Any, **kwargs: Any) -> Any: calls["temp"] += 1; return _default_ops(schema).temp_factory(*args, **kwargs)
    def count_replace(*args: Any, **kwargs: Any) -> Any: calls["replace"] += 1; return _default_ops(schema).replace(*args, **kwargs)
    assert schema.export_schema(target, "check", replace(ops, temp_factory=count_temp, replace=count_replace), trusted_root=tmp_path) == 2
    assert calls == {"temp": 0, "replace": 0}; _assert_same_mtime(target, before)


@pytest.mark.parametrize("race", ["missing_created", "existing_deleted", "existing_regular", "existing_symlink"])
def test_pre_replace_target_state_races_never_replace_competitor(tmp_path: Path, race: str) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"
    referent = tmp_path / "referent"
    referent.write_bytes(b"referent")
    if race != "missing_created":
        target.write_bytes(b"old")
    ops = _default_ops(schema)
    original_factory = ops.temp_factory
    replace_calls = 0
    staged_paths: list[Path] = []
    raced = False

    class CloseThenRace:
        def __init__(self, handle: Any) -> None:
            self.handle = handle

        def write(self, data: bytes) -> int:
            return self.handle.write(data)

        def flush(self) -> None:
            self.handle.flush()

        def fileno(self) -> int:
            return self.handle.fileno()

        def close(self) -> None:
            nonlocal raced
            self.handle.close()
            if raced:
                return
            raced = True
            if race == "missing_created":
                target.write_bytes(b"competitor")
            elif race == "existing_deleted":
                target.unlink()
            elif race == "existing_regular":
                target.unlink()
                target.write_bytes(b"competitor")
            else:
                target.unlink()
                target.symlink_to(referent)

    def factory(parent: Path) -> Any:
        staged = original_factory(parent)
        staged_paths.append(staged.path)
        return type(staged)(staged.path, CloseThenRace(staged.handle))

    def forbidden_replace(source: Path, destination: Path) -> None:
        nonlocal replace_calls
        del source, destination
        replace_calls += 1

    ops = replace(ops, temp_factory=factory, replace=forbidden_replace)
    assert schema.export_schema(target, "check-or-write", ops, trusted_root=tmp_path) == 2
    assert replace_calls == 0
    assert staged_paths and not staged_paths[0].exists()
    if race in ("missing_created", "existing_regular"):
        assert target.read_bytes() == b"competitor"
    elif race == "existing_deleted":
        assert not target.exists()
    else:
        assert target.is_symlink()
        assert referent.read_bytes() == b"referent"


@pytest.mark.parametrize("race", ["identity", "symlink"])
def test_pre_replace_parent_state_races_cleanup_without_replace(tmp_path: Path, race: str) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"
    target.write_bytes(b"old")
    ops = _default_ops(schema)
    original_factory = ops.temp_factory
    original_lstat = ops.lstat
    staged_closed = False
    staged_close_calls = 0
    staged_paths: list[Path] = []
    replace_calls = 0

    class CloseThenChangeParentView:
        def __init__(self, handle: Any) -> None:
            self.handle = handle

        def write(self, data: bytes) -> int:
            return self.handle.write(data)

        def flush(self) -> None:
            self.handle.flush()

        def fileno(self) -> int:
            return self.handle.fileno()

        def close(self) -> None:
            nonlocal staged_close_calls, staged_closed
            staged_close_calls += 1
            self.handle.close()
            staged_closed = True

    def factory(parent: Path) -> Any:
        staged = original_factory(parent)
        staged_paths.append(staged.path)
        return type(staged)(staged.path, CloseThenChangeParentView(staged.handle))

    def racing_lstat(path: Path) -> Any:
        snapshot = original_lstat(path)
        if staged_closed and path == tmp_path:
            if race == "identity":
                return type(snapshot)(snapshot.mode, FileIdentity("posix", (999, 999)))
            return type(snapshot)(stat.S_IFLNK, snapshot.identity)
        return snapshot

    def forbidden_replace(source: Path, destination: Path) -> None:
        nonlocal replace_calls
        del source, destination
        replace_calls += 1

    ops = replace(ops, temp_factory=factory, lstat=racing_lstat, replace=forbidden_replace)
    assert schema.export_schema(target, "check-or-write", ops, trusted_root=tmp_path) == 2
    assert replace_calls == 0
    assert staged_close_calls == 1
    assert staged_paths and not staged_paths[0].exists()
    assert target.read_bytes() == b"old"


def test_success_order_and_single_replace(tmp_path: Path) -> None:
    atomic, schema, _ = load_schema_export_contract()
    del atomic
    target = tmp_path / "action.schema.json"
    target.write_bytes(b"old")
    events: list[str] = []
    ops = _default_ops(schema)
    original_lstat = ops.lstat
    original_open_read = ops.open_read_no_follow
    original_factory = ops.temp_factory
    original_replace = ops.replace
    original_open_parent = ops.open_parent_no_follow

    def observed_lstat(path: Path) -> Any:
        events.append("lstat-target" if path == target else "lstat-parent")
        return original_lstat(path)

    class OrderedRead:
        def __init__(self, handle: Any) -> None:
            self.handle = handle

        def fstat_identity(self) -> Any:
            events.append("target-fstat")
            return self.handle.fstat_identity()

        def read(self) -> bytes:
            events.append("target-read")
            return self.handle.read()

        def close(self) -> None:
            events.append("target-close")
            self.handle.close()

    def open_read(path: Path) -> Any:
        events.append("target-open")
        return OrderedRead(original_open_read(path))

    class OrderedTemp:
        def __init__(self, handle: Any) -> None:
            self.handle = handle

        def write(self, data: bytes) -> int:
            events.append("write")
            return self.handle.write(data)

        def flush(self) -> None:
            events.append("flush")
            self.handle.flush()

        def fileno(self) -> int:
            events.append("fileno")
            return self.handle.fileno()

        def close(self) -> None:
            events.append("staged-close")
            self.handle.close()

    staged_paths: list[Path] = []

    def factory(parent: Path) -> Any:
        events.append("temp")
        staged = original_factory(parent)
        staged_paths.append(staged.path)
        return type(staged)(staged.path, OrderedTemp(staged.handle))

    def do_replace(source: Path, destination: Path) -> None:
        events.append("replace")
        assert (source, destination) == (staged_paths[0], target)
        original_replace(source, destination)

    def do_fsync(fd: int) -> None:
        events.append("file-fsync")
        __import__("os").fsync(fd)

    class OrderedParent:
        def __init__(self, handle: Any) -> None:
            self.handle = handle

        def fstat_identity(self) -> Any:
            events.append("parent-fstat")
            return self.handle.fstat_identity()

        def sync_entry(self) -> None:
            events.append("parent-sync")
            self.handle.sync_entry()

        def close(self) -> None:
            events.append("parent-close")
            self.handle.close()

    def open_parent(path: Path) -> Any:
        events.append("parent-open")
        return OrderedParent(original_open_parent(path))

    observed_ops = replace(
        ops,
        lstat=observed_lstat,
        open_read_no_follow=open_read,
        temp_factory=factory,
        replace=do_replace,
        fsync=do_fsync,
        open_parent_no_follow=open_parent,
    )
    assert schema.export_schema(target, "check-or-write", observed_ops, trusted_root=tmp_path) == 0
    staged_close = events.index("staged-close")
    replace_index = events.index("replace")
    assert events[events.index("write"):staged_close + 1] == [
        "write", "flush", "fileno", "file-fsync", "staged-close",
    ]
    assert "lstat-target" in events[staged_close + 1:replace_index]
    assert "target-open" in events[staged_close + 1:replace_index]
    assert "target-fstat" in events[staged_close + 1:replace_index]
    assert "target-read" in events[staged_close + 1:replace_index]
    assert "target-close" in events[staged_close + 1:replace_index]
    assert events[replace_index:] == [
        "replace", "lstat-parent", "parent-open", "parent-fstat", "parent-sync", "parent-close",
    ]
    assert events.count("replace") == 1

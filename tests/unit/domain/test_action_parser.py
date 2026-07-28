"""Contract tests for the public, side-effect-free action parser.

Production imports intentionally stay inside ``load_action_parser_contract`` so
the test-owned fixtures and mutation oracle remain runnable during RED.
"""

from __future__ import annotations

import ast
import copy
import importlib
import logging
import os
import socket
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest


JsonObject = dict[str, object]

COMMON_FIELDS = (
    "action_id",
    "run_id",
    "generation",
    "kind",
    "reason_summary",
    "payload",
)

PAYLOAD_FIELDS: dict[str, tuple[str, ...]] = {
    "list_directory": ("root_id", "relative_path", "max_depth", "max_entries"),
    "read_text": ("root_id", "relative_path", "start_line", "end_line", "max_bytes"),
    "search_literal": ("root_id", "relative_path", "query", "globs", "max_results"),
    "apply_patch": ("root_id", "relative_path", "base_sha256", "hunks"),
    "git_inspect": ("operation",),
    "run_command": (
        "template_id",
        "arguments",
        "cwd_root_id",
        "cwd_relative_path",
        "timeout_ms",
    ),
    "run_validation": ("validator_id", "target_paths"),
    "request_review": ("summary", "uncovered"),
}

ACTION_CODES = {
    "ACTION_SHAPE_INVALID",
    "ACTION_FIELD_REQUIRED",
    "ACTION_FIELD_UNKNOWN",
    "ACTION_TYPE_INVALID",
    "ACTION_BOUND_INVALID",
    "ACTION_PATTERN_INVALID",
    "ACTION_ENUM_INVALID",
    "ACTION_RELATION_INVALID",
}

STRING_TYPE_CASES: tuple[tuple[str, tuple[str | int, ...], str], ...] = (
    ("list_directory", ("action_id",), "/action_id"),
    ("list_directory", ("run_id",), "/run_id"),
    ("list_directory", ("reason_summary",), "/reason_summary"),
    ("list_directory", ("payload", "root_id"), "/payload/root_id"),
    ("list_directory", ("payload", "relative_path"), "/payload/relative_path"),
    ("read_text", ("payload", "root_id"), "/payload/root_id"),
    ("read_text", ("payload", "relative_path"), "/payload/relative_path"),
    ("search_literal", ("payload", "root_id"), "/payload/root_id"),
    ("search_literal", ("payload", "relative_path"), "/payload/relative_path"),
    ("search_literal", ("payload", "query"), "/payload/query"),
    ("apply_patch", ("payload", "root_id"), "/payload/root_id"),
    ("apply_patch", ("payload", "relative_path"), "/payload/relative_path"),
    ("apply_patch", ("payload", "base_sha256"), "/payload/base_sha256"),
    (
        "apply_patch",
        ("payload", "hunks", 0, "expected_text"),
        "/payload/hunks/0/expected_text",
    ),
    (
        "apply_patch",
        ("payload", "hunks", 0, "replacement_text"),
        "/payload/hunks/0/replacement_text",
    ),
    ("git_inspect", ("payload", "operation"), "/payload/operation"),
    ("run_command", ("payload", "template_id"), "/payload/template_id"),
    ("run_command", ("payload", "cwd_root_id"), "/payload/cwd_root_id"),
    (
        "run_command",
        ("payload", "cwd_relative_path"),
        "/payload/cwd_relative_path",
    ),
    ("run_validation", ("payload", "validator_id"), "/payload/validator_id"),
    ("request_review", ("payload", "summary"), "/payload/summary"),
)

STRICT_INT_CASES: tuple[tuple[str, tuple[str | int, ...], int, int | None], ...] = (
    ("list_directory", ("generation",), 0, None),
    ("list_directory", ("payload", "max_depth"), 0, 16),
    ("list_directory", ("payload", "max_entries"), 1, 1000),
    ("read_text", ("payload", "start_line"), 1, None),
    ("read_text", ("payload", "end_line"), 1, None),
    ("read_text", ("payload", "max_bytes"), 1, 1_048_576),
    ("apply_patch", ("payload", "hunks", 0, "start_line"), 1, None),
    ("apply_patch", ("payload", "hunks", 0, "delete_line_count"), 0, 10_000),
    ("search_literal", ("payload", "max_results"), 1, 500),
    ("run_command", ("payload", "timeout_ms"), 1000, 600_000),
)

NUL_CASES: tuple[tuple[str, tuple[str | int, ...], str], ...] = (
    ("list_directory", ("action_id",), "/action_id"),
    ("list_directory", ("run_id",), "/run_id"),
    ("list_directory", ("reason_summary",), "/reason_summary"),
    ("list_directory", ("kind",), "/kind"),
    ("list_directory", ("payload", "root_id"), "/payload/root_id"),
    ("list_directory", ("payload", "relative_path"), "/payload/relative_path"),
    ("read_text", ("payload", "root_id"), "/payload/root_id"),
    ("read_text", ("payload", "relative_path"), "/payload/relative_path"),
    ("search_literal", ("payload", "root_id"), "/payload/root_id"),
    ("search_literal", ("payload", "relative_path"), "/payload/relative_path"),
    ("search_literal", ("payload", "query"), "/payload/query"),
    ("search_literal", ("payload", "globs", 0), "/payload/globs/0"),
    ("apply_patch", ("payload", "root_id"), "/payload/root_id"),
    ("apply_patch", ("payload", "relative_path"), "/payload/relative_path"),
    ("apply_patch", ("payload", "base_sha256"), "/payload/base_sha256"),
    (
        "apply_patch",
        ("payload", "hunks", 0, "expected_text"),
        "/payload/hunks/0/expected_text",
    ),
    (
        "apply_patch",
        ("payload", "hunks", 0, "replacement_text"),
        "/payload/hunks/0/replacement_text",
    ),
    ("git_inspect", ("payload", "operation"), "/payload/operation"),
    ("run_command", ("payload", "template_id"), "/payload/template_id"),
    ("run_command", ("payload", "cwd_root_id"), "/payload/cwd_root_id"),
    (
        "run_command",
        ("payload", "cwd_relative_path"),
        "/payload/cwd_relative_path",
    ),
    ("run_validation", ("payload", "validator_id"), "/payload/validator_id"),
    ("run_validation", ("payload", "target_paths", 0), "/payload/target_paths/0"),
    ("request_review", ("payload", "summary"), "/payload/summary"),
    ("request_review", ("payload", "uncovered", 0), "/payload/uncovered/0"),
)


def valid_actions() -> dict[str, JsonObject]:
    """Return fresh, handwritten candidates for all eight JSON contracts."""

    common: JsonObject = {
        "action_id": "action-1",
        "run_id": "run-1",
        "generation": 0,
        "reason_summary": "Inspect the requested source safely.",
    }
    payloads: dict[str, JsonObject] = {
        "list_directory": {
            "root_id": "project",
            "relative_path": "",
            "max_depth": 0,
            "max_entries": 1,
        },
        "read_text": {
            "root_id": "project",
            "relative_path": "README.md",
            "start_line": 1,
            "end_line": 1,
            "max_bytes": 1,
        },
        "search_literal": {
            "root_id": "project",
            "relative_path": "",
            "query": "needle",
            "globs": ["*.py"],
            "max_results": 1,
        },
        "apply_patch": {
            "root_id": "workspace",
            "relative_path": "src/example.py",
            "base_sha256": "a" * 64,
            "hunks": [
                {
                    "start_line": 1,
                    "delete_line_count": 0,
                    "expected_text": "",
                    "replacement_text": "replacement",
                }
            ],
        },
        "git_inspect": {"operation": "status"},
        "run_command": {
            "template_id": "pytest-unit",
            "arguments": {"target": "tests/unit"},
            "cwd_root_id": "project",
            "cwd_relative_path": "",
            "timeout_ms": 1000,
        },
        "run_validation": {
            "validator_id": "unit-test",
            "target_paths": ["src/yagcode"],
        },
        "request_review": {
            "summary": "Implementation and focused tests are ready for review.",
            "uncovered": ["manual smoke test"],
        },
    }
    return {
        kind: {**common, "kind": kind, "payload": copy.deepcopy(payload)}
        for kind, payload in payloads.items()
    }


def mutate(candidate: JsonObject, path: tuple[str | int, ...], value: object) -> JsonObject:
    """Return a deep-copied candidate with an exact mapping/list slot replaced."""

    result = copy.deepcopy(candidate)
    if not path:
        raise ValueError("a mutation path must not be empty")
    current: object = result
    for segment in path[:-1]:
        if isinstance(current, dict) and isinstance(segment, str):
            current = current[segment]
        elif isinstance(current, list) and isinstance(segment, int):
            current = current[segment]
        else:
            raise TypeError("path does not select a mapping key or list index")
    final = path[-1]
    if isinstance(current, dict) and isinstance(final, str):
        current[final] = value
    elif isinstance(current, list) and isinstance(final, int):
        current[final] = value
    else:
        raise TypeError("path does not select a writable mapping key or list index")
    return result


def without(candidate: JsonObject, path: tuple[str | int, ...]) -> JsonObject:
    """Return a deep-copied candidate with one exact mapping key removed."""

    result = copy.deepcopy(candidate)
    current: object = result
    for segment in path[:-1]:
        if isinstance(current, dict) and isinstance(segment, str):
            current = current[segment]
        elif isinstance(current, list) and isinstance(segment, int):
            current = current[segment]
        else:
            raise TypeError("path does not select a mapping key or list index")
    final = path[-1]
    if not isinstance(current, dict) or not isinstance(final, str):
        raise TypeError("only mapping keys may be removed")
    del current[final]
    return result


def load_action_parser_contract() -> tuple[type[Any], type[Any], type[Any], type[Any]]:
    """Import production only at case runtime, preserving collection-time RED."""

    parser_module = importlib.import_module("yagcode.domain.action_parser")
    return (
        parser_module.ActionParser,
        parser_module.ActionParseFailure,
        parser_module.ActionParseIssue,
        parser_module.ActionParseSuccess,
    )


def parse(candidate: object) -> tuple[object, type[Any], type[Any], type[Any]]:
    parser_type, failure_type, issue_type, success_type = load_action_parser_contract()
    return parser_type().parse(candidate), failure_type, issue_type, success_type


def assert_failure(candidate: object, expected_code: str, expected_path: str | None = None) -> object:
    result, failure_type, _issue_type, _success_type = parse(candidate)
    assert isinstance(result, failure_type)
    assert result.reason_code == "ACTION_CANDIDATE_INVALID"
    assert 1 <= len(result.issues) <= 32
    assert all(issue.code in ACTION_CODES for issue in result.issues)
    assert expected_code in {issue.code for issue in result.issues}
    if expected_path is not None:
        assert (expected_path, expected_code) in {(issue.path, issue.code) for issue in result.issues}
    return result


def test_owned_action_fixtures_and_mutation_helper() -> None:
    """The handwritten fixture/oracle is useful even when production is absent."""

    fixtures = valid_actions()
    assert tuple(fixtures) == tuple(PAYLOAD_FIELDS)
    assert fixtures["request_review"]["payload"] == {
        "summary": "Implementation and focused tests are ready for review.",
        "uncovered": ["manual smoke test"],
    }
    assert mutate(fixtures["search_literal"], ("payload", "globs", 0), "*.md")["payload"] == {
        "root_id": "project",
        "relative_path": "",
        "query": "needle",
        "globs": ["*.md"],
        "max_results": 1,
    }
    assert "root_id" in fixtures["search_literal"]["payload"]
    with pytest.raises(KeyError):
        without(fixtures["read_text"], ("payload", "missing"))
    with pytest.raises(TypeError):
        mutate(fixtures["read_text"], ("payload", 0), "value")
    with pytest.raises(ValueError):
        mutate(fixtures["read_text"], (), "value")


@pytest.mark.parametrize("kind", tuple(PAYLOAD_FIELDS))
def test_public_parser_accepts_each_exact_action_kind(kind: str) -> None:
    result, _failure_type, _issue_type, success_type = parse(valid_actions()[kind])
    assert isinstance(result, success_type)
    assert result.action.kind == kind


@pytest.mark.parametrize(
    ("kind", "field"),
    [(kind, field) for kind in PAYLOAD_FIELDS for field in COMMON_FIELDS],
)
def test_public_parser_requires_every_common_field(kind: str, field: str) -> None:
    assert_failure(without(valid_actions()[kind], (field,)), "ACTION_FIELD_REQUIRED", f"/{field}")


@pytest.mark.parametrize("kind", tuple(PAYLOAD_FIELDS))
def test_public_parser_rejects_top_level_unknown_fields(kind: str) -> None:
    candidate = valid_actions()[kind]
    candidate["untrusted/top~field"] = "must-not-leak"
    assert_failure(candidate, "ACTION_FIELD_UNKNOWN", "/*")


@pytest.mark.parametrize(
    ("kind", "field"),
    [(kind, field) for kind, fields in PAYLOAD_FIELDS.items() for field in fields],
)
def test_public_parser_requires_each_payload_field(kind: str, field: str) -> None:
    assert_failure(
        without(valid_actions()[kind], ("payload", field)),
        "ACTION_FIELD_REQUIRED",
        f"/payload/{field}",
    )


@pytest.mark.parametrize("kind", tuple(PAYLOAD_FIELDS))
def test_public_parser_rejects_unknown_payload_field_without_echoing_key(kind: str) -> None:
    candidate = valid_actions()[kind]
    payload = candidate["payload"]
    assert isinstance(payload, dict)
    payload["credential/like~field"] = "provider response prompt secret"
    result = assert_failure(candidate, "ACTION_FIELD_UNKNOWN", "/payload/*")
    rendered = repr(result)
    assert "credential/like~field" not in rendered
    assert "provider response prompt secret" not in rendered


@pytest.mark.parametrize("field", ("start_line", "delete_line_count", "expected_text", "replacement_text"))
def test_public_parser_requires_and_closes_each_nested_hunk_field(field: str) -> None:
    candidate = valid_actions()["apply_patch"]
    assert_failure(
        without(candidate, ("payload", "hunks", 0, field)),
        "ACTION_FIELD_REQUIRED",
        f"/payload/hunks/0/{field}",
    )
    candidate = valid_actions()["apply_patch"]
    hunks = candidate["payload"]
    assert isinstance(hunks, dict)
    first_hunk = hunks["hunks"]
    assert isinstance(first_hunk, list) and isinstance(first_hunk[0], dict)
    first_hunk[0]["unknown"] = "value"
    assert_failure(candidate, "ACTION_FIELD_UNKNOWN", "/payload/hunks/0/*")


@pytest.mark.parametrize(
    ("path", "bad_value", "code"),
    [
        (("action_id",), "", "ACTION_BOUND_INVALID"),
        (("run_id",), "x" * 129, "ACTION_BOUND_INVALID"),
        (("reason_summary",), 1, "ACTION_TYPE_INVALID"),
        (("generation",), True, "ACTION_TYPE_INVALID"),
        (("generation",), 0.0, "ACTION_TYPE_INVALID"),
        (("generation",), "0", "ACTION_TYPE_INVALID"),
        (("generation",), -1, "ACTION_BOUND_INVALID"),
        (("kind",), "LIST_DIRECTORY", "ACTION_ENUM_INVALID"),
    ],
)
def test_public_parser_enforces_common_strict_types_and_bounds(
    path: tuple[str | int, ...], bad_value: object, code: str
) -> None:
    assert_failure(mutate(valid_actions()["list_directory"], path, bad_value), code)


@pytest.mark.parametrize(
    ("path", "bad_value", "code"),
    [
        (("payload", "relative_path"), 1, "ACTION_TYPE_INVALID"),
        (("payload", "relative_path"), "x" * 1025, "ACTION_BOUND_INVALID"),
        (("payload", "max_depth"), True, "ACTION_TYPE_INVALID"),
        (("payload", "max_depth"), 16.0, "ACTION_TYPE_INVALID"),
        (("payload", "max_depth"), -1, "ACTION_BOUND_INVALID"),
        (("payload", "max_depth"), 17, "ACTION_BOUND_INVALID"),
        (("payload", "max_entries"), 0, "ACTION_BOUND_INVALID"),
        (("payload", "max_entries"), 1001, "ACTION_BOUND_INVALID"),
    ],
)
def test_list_directory_strict_contract(
    path: tuple[str | int, ...], bad_value: object, code: str
) -> None:
    assert_failure(mutate(valid_actions()["list_directory"], path, bad_value), code)


@pytest.mark.parametrize(
    ("path", "bad_value", "code"),
    [
        (("payload", "relative_path"), "", "ACTION_BOUND_INVALID"),
        (("payload", "start_line"), True, "ACTION_TYPE_INVALID"),
        (("payload", "start_line"), 0, "ACTION_BOUND_INVALID"),
        (("payload", "end_line"), 0, "ACTION_BOUND_INVALID"),
        (("payload", "max_bytes"), 0, "ACTION_BOUND_INVALID"),
        (("payload", "max_bytes"), 1_048_577, "ACTION_BOUND_INVALID"),
    ],
)
def test_read_text_strict_bounds_and_types(
    path: tuple[str | int, ...], bad_value: object, code: str
) -> None:
    assert_failure(mutate(valid_actions()["read_text"], path, bad_value), code)


def test_read_text_enforces_end_line_relation_and_equal_boundary() -> None:
    assert_failure(
        mutate(valid_actions()["read_text"], ("payload", "end_line"), 0),
        "ACTION_BOUND_INVALID",
    )
    assert_failure(
        mutate(valid_actions()["read_text"], ("payload", "end_line"), 0),
        "ACTION_BOUND_INVALID",
    )
    relation_candidate = valid_actions()["read_text"]
    payload = relation_candidate["payload"]
    assert isinstance(payload, dict)
    payload["start_line"] = 2
    payload["end_line"] = 1
    assert_failure(relation_candidate, "ACTION_RELATION_INVALID", "/payload")
    result, _failure_type, _issue_type, success_type = parse(valid_actions()["read_text"])
    assert isinstance(result, success_type)


@pytest.mark.parametrize(
    ("path", "bad_value", "code"),
    [
        (("payload", "query"), "", "ACTION_BOUND_INVALID"),
        (("payload", "query"), "q" * 513, "ACTION_BOUND_INVALID"),
        (("payload", "globs"), {}, "ACTION_TYPE_INVALID"),
        (("payload", "globs"), [], "ACTION_FIELD_REQUIRED"),
        (("payload", "globs"), [""], "ACTION_BOUND_INVALID"),
        (("payload", "globs"), ["x" * 129], "ACTION_BOUND_INVALID"),
        (("payload", "globs"), ["x"] * 21, "ACTION_BOUND_INVALID"),
        (("payload", "max_results"), 0, "ACTION_BOUND_INVALID"),
        (("payload", "max_results"), 501, "ACTION_BOUND_INVALID"),
    ],
)
def test_search_literal_strict_contract(
    path: tuple[str | int, ...], bad_value: object, code: str
) -> None:
    candidate = valid_actions()["search_literal"]
    if path == ("payload", "globs") and bad_value == []:
        result, _failure_type, _issue_type, success_type = parse(mutate(candidate, path, bad_value))
        assert isinstance(result, success_type)
        return
    assert_failure(mutate(candidate, path, bad_value), code)


@pytest.mark.parametrize(
    ("path", "bad_value", "code"),
    [
        (("payload", "relative_path"), "", "ACTION_BOUND_INVALID"),
        (("payload", "base_sha256"), "a" * 63, "ACTION_PATTERN_INVALID"),
        (("payload", "base_sha256"), "a" * 65, "ACTION_PATTERN_INVALID"),
        (("payload", "base_sha256"), "A" * 64, "ACTION_PATTERN_INVALID"),
        (("payload", "base_sha256"), "g" * 64, "ACTION_PATTERN_INVALID"),
        (("payload", "hunks"), [], "ACTION_BOUND_INVALID"),
        (("payload", "hunks"), [{}] * 51, "ACTION_BOUND_INVALID"),
        (("payload", "hunks", 0, "start_line"), 0, "ACTION_BOUND_INVALID"),
        (("payload", "hunks", 0, "delete_line_count"), -1, "ACTION_BOUND_INVALID"),
        (("payload", "hunks", 0, "delete_line_count"), 10_001, "ACTION_BOUND_INVALID"),
        pytest.param(
            ("payload", "hunks", 0, "expected_text"),
            "x" * 65_537,
            "ACTION_BOUND_INVALID",
            id="expected_text_too_long",
        ),
        pytest.param(
            ("payload", "hunks", 0, "replacement_text"),
            "x" * 65_537,
            "ACTION_BOUND_INVALID",
            id="replacement_text_too_long",
        ),
    ],
)
def test_apply_patch_strict_contract(
    path: tuple[str | int, ...], bad_value: object, code: str
) -> None:
    assert_failure(mutate(valid_actions()["apply_patch"], path, bad_value), code)


@pytest.mark.parametrize("operation", ("head", "status", "index", "worktree", "common_dir"))
def test_git_inspect_accepts_only_the_five_exact_operations(operation: str) -> None:
    result, _failure_type, _issue_type, success_type = parse(
        mutate(valid_actions()["git_inspect"], ("payload", "operation"), operation)
    )
    assert isinstance(result, success_type)


@pytest.mark.parametrize("operation", ("HEAD", " status", "status ", "log", "common-dir"))
def test_git_inspect_rejects_aliases_whitespace_and_case(operation: str) -> None:
    assert_failure(
        mutate(valid_actions()["git_inspect"], ("payload", "operation"), operation),
        "ACTION_ENUM_INVALID",
        "/payload/operation",
    )


@pytest.mark.parametrize(
    ("path", "bad_value", "code"),
    [
        (("payload", "template_id"), "", "ACTION_BOUND_INVALID"),
        (("payload", "template_id"), "x" * 129, "ACTION_BOUND_INVALID"),
        (("payload", "arguments"), [], "ACTION_TYPE_INVALID"),
        (("payload", "arguments"), {"x" * 65: "value"}, "ACTION_BOUND_INVALID"),
        (("payload", "arguments"), {"key": "x" * 1025}, "ACTION_BOUND_INVALID"),
        (("payload", "arguments"), {str(index): "v" for index in range(33)}, "ACTION_BOUND_INVALID"),
        (("payload", "timeout_ms"), True, "ACTION_TYPE_INVALID"),
        (("payload", "timeout_ms"), 999, "ACTION_BOUND_INVALID"),
        (("payload", "timeout_ms"), 600_001, "ACTION_BOUND_INVALID"),
    ],
)
def test_run_command_strict_contract_and_dynamic_arguments(
    path: tuple[str | int, ...], bad_value: object, code: str
) -> None:
    assert_failure(mutate(valid_actions()["run_command"], path, bad_value), code)


@pytest.mark.parametrize(
    ("path", "bad_value", "code"),
    [
        (("payload", "validator_id"), "", "ACTION_BOUND_INVALID"),
        (("payload", "target_paths"), [], "ACTION_BOUND_INVALID"),
        (("payload", "target_paths"), ["x"] * 101, "ACTION_BOUND_INVALID"),
        (("payload", "target_paths"), [""], "ACTION_BOUND_INVALID"),
        (("payload", "summary"), "", "ACTION_BOUND_INVALID"),
        (("payload", "summary"), "x" * 4001, "ACTION_BOUND_INVALID"),
        (("payload", "uncovered"), {}, "ACTION_TYPE_INVALID"),
        (("payload", "uncovered"), ["x"] * 101, "ACTION_BOUND_INVALID"),
        (("payload", "uncovered"), [""], "ACTION_BOUND_INVALID"),
    ],
)
def test_validation_and_review_strict_contract(
    path: tuple[str | int, ...], bad_value: object, code: str
) -> None:
    kind = "run_validation" if path[1] in {"validator_id", "target_paths"} else "request_review"
    assert_failure(mutate(valid_actions()[kind], path, bad_value), code)


def test_explicit_empty_collections_are_valid_but_must_be_present() -> None:
    for kind, field in (("search_literal", "globs"), ("run_command", "arguments"), ("request_review", "uncovered")):
        candidate = mutate(valid_actions()[kind], ("payload", field), [] if field != "arguments" else {})
        result, _failure_type, _issue_type, success_type = parse(candidate)
        assert isinstance(result, success_type)
        assert_failure(without(candidate, ("payload", field)), "ACTION_FIELD_REQUIRED", f"/payload/{field}")


@pytest.mark.parametrize(("kind", "path", "expected_path"), STRING_TYPE_CASES)
def test_every_declared_string_field_rejects_an_incorrect_json_type(
    kind: str, path: tuple[str | int, ...], expected_path: str
) -> None:
    assert_failure(mutate(valid_actions()[kind], path, 1), "ACTION_TYPE_INVALID", expected_path)


def test_dynamic_argument_keys_and_values_reject_incorrect_json_types() -> None:
    assert_failure(
        mutate(valid_actions()["run_command"], ("payload", "arguments"), {1: "value"}),
        "ACTION_TYPE_INVALID",
        "/payload/arguments/*",
    )
    assert_failure(
        mutate(valid_actions()["run_command"], ("payload", "arguments"), {"key": 1}),
        "ACTION_TYPE_INVALID",
        "/payload/arguments/*",
    )


@pytest.mark.parametrize(("kind", "path", "minimum", "maximum"), STRICT_INT_CASES)
@pytest.mark.parametrize("bad_value", (True, 1.0, "1"))
def test_every_strict_integer_rejects_bool_float_and_numeric_string(
    kind: str, path: tuple[str | int, ...], minimum: int, maximum: int | None, bad_value: object
) -> None:
    del minimum, maximum
    assert_failure(mutate(valid_actions()[kind], path, bad_value), "ACTION_TYPE_INVALID")


@pytest.mark.parametrize(("kind", "path", "minimum", "maximum"), STRICT_INT_CASES)
def test_every_strict_integer_enforces_adjacent_bounds(
    kind: str, path: tuple[str | int, ...], minimum: int, maximum: int | None
) -> None:
    assert_failure(mutate(valid_actions()[kind], path, minimum - 1), "ACTION_BOUND_INVALID")
    result, _failure_type, _issue_type, success_type = parse(
        mutate(valid_actions()[kind], path, minimum)
    )
    assert isinstance(result, success_type)
    if maximum is not None:
        result, _failure_type, _issue_type, success_type = parse(
            mutate(valid_actions()[kind], path, maximum)
        )
        assert isinstance(result, success_type)
        assert_failure(
            mutate(valid_actions()[kind], path, maximum + 1), "ACTION_BOUND_INVALID"
        )


@pytest.mark.parametrize(
    ("kind", "field", "minimum", "maximum"),
    (
        ("search_literal", "globs", 0, 20),
        ("apply_patch", "hunks", 1, 50),
        ("run_validation", "target_paths", 1, 100),
        ("request_review", "uncovered", 0, 100),
    ),
)
def test_every_list_collection_has_strict_container_item_and_count_contract(
    kind: str, field: str, minimum: int, maximum: int
) -> None:
    candidate = valid_actions()[kind]
    payload = candidate["payload"]
    assert isinstance(payload, dict)
    original_items = payload[field]
    assert isinstance(original_items, list) and original_items
    item = copy.deepcopy(original_items[0])
    collection_path: tuple[str | int, ...] = ("payload", field)
    assert_failure(mutate(candidate, collection_path, {}), "ACTION_TYPE_INVALID", f"/payload/{field}")
    assert_failure(
        mutate(candidate, collection_path, [1]), "ACTION_TYPE_INVALID", f"/payload/{field}/0"
    )
    empty_result, _failure_type, _issue_type, success_type = parse(
        mutate(candidate, collection_path, [])
    )
    if minimum == 0:
        assert isinstance(empty_result, success_type)
    else:
        assert_failure(mutate(candidate, collection_path, []), "ACTION_BOUND_INVALID")
    one_result, _failure_type, _issue_type, success_type = parse(
        mutate(candidate, collection_path, [item])
    )
    assert isinstance(one_result, success_type)
    maximum_result, _failure_type, _issue_type, success_type = parse(
        mutate(candidate, collection_path, [item] * maximum)
    )
    assert isinstance(maximum_result, success_type)
    assert_failure(
        mutate(candidate, collection_path, [item] * (maximum + 1)), "ACTION_BOUND_INVALID"
    )
    assert_failure(
        without(candidate, collection_path), "ACTION_FIELD_REQUIRED", f"/payload/{field}"
    )


def test_arguments_collection_has_strict_object_key_value_count_and_required_contract() -> None:
    candidate = valid_actions()["run_command"]
    path: tuple[str | int, ...] = ("payload", "arguments")
    assert_failure(mutate(candidate, path, []), "ACTION_TYPE_INVALID", "/payload/arguments")
    assert_failure(mutate(candidate, path, {1: "value"}), "ACTION_TYPE_INVALID", "/payload/arguments/*")
    assert_failure(mutate(candidate, path, {"key": 1}), "ACTION_TYPE_INVALID", "/payload/arguments/*")
    for count in (0, 1, 32):
        result, _failure_type, _issue_type, success_type = parse(
            mutate(candidate, path, {str(index): "value" for index in range(count)})
        )
        assert isinstance(result, success_type)
    assert_failure(
        mutate(candidate, path, {str(index): "value" for index in range(33)}),
        "ACTION_BOUND_INVALID",
    )
    assert_failure(without(candidate, path), "ACTION_FIELD_REQUIRED", "/payload/arguments")


@pytest.mark.parametrize(
    ("kind", "path"),
    [
        ("list_directory", ("reason_summary",)),
        ("read_text", ("payload", "relative_path")),
        ("search_literal", ("payload", "globs", 0)),
        ("run_command", ("payload", "arguments")),
    ],
)
def test_recursive_nul_rejection_covers_strings_arrays_and_dynamic_values(
    kind: str, path: tuple[str | int, ...]
) -> None:
    bad_value: object = "bad\x00value"
    if path == ("payload", "arguments"):
        bad_value = {"dynamic": "bad\x00value"}
    assert_failure(mutate(valid_actions()[kind], path, bad_value), "ACTION_PATTERN_INVALID")


def test_recursive_nul_rejection_covers_dynamic_mapping_keys() -> None:
    assert_failure(
        mutate(valid_actions()["run_command"], ("payload", "arguments"), {"bad\x00key": "value"}),
        "ACTION_PATTERN_INVALID",
        "/payload/arguments/*",
    )


@pytest.mark.parametrize(("kind", "path", "expected_path"), NUL_CASES)
def test_every_declared_string_field_rejects_nul_without_leaking_its_value(
    kind: str, path: tuple[str | int, ...], expected_path: str
) -> None:
    canary = "candidate-value-input-prompt-provider-secret"
    result = assert_failure(
        mutate(valid_actions()[kind], path, f"{canary}\x00"),
        "ACTION_PATTERN_INVALID",
        expected_path,
    )
    assert canary not in repr(result)
    assert canary not in str(result)


def test_dynamic_argument_key_and_value_nul_paths_are_safe_and_value_free() -> None:
    canary = "candidate-value-input-prompt-provider-secret"
    for arguments in ({f"{canary}\x00": "value"}, {"key": f"{canary}\x00"}):
        result = assert_failure(
            mutate(valid_actions()["run_command"], ("payload", "arguments"), arguments),
            "ACTION_PATTERN_INVALID",
            "/payload/arguments/*",
        )
        assert canary not in repr(result)
        assert canary not in str(result)


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        True,
        1,
        1.0,
        "action",
        [],
        {"actions": [valid_actions()["list_directory"]]},
        {"actions": [valid_actions()["list_directory"], valid_actions()["read_text"]]},
    ],
)
def test_root_shape_wrapper_and_multiple_actions_are_never_unwrapped(candidate: object) -> None:
    assert_failure(candidate, "ACTION_SHAPE_INVALID", "")


def test_unknown_kind_and_payload_at_wrong_level_are_not_repaired() -> None:
    assert_failure(
        mutate(valid_actions()["list_directory"], ("kind",), "shell_command"),
        "ACTION_ENUM_INVALID",
        "/kind",
    )
    candidate = valid_actions()["list_directory"]
    payload = candidate.pop("payload")
    assert isinstance(payload, dict)
    candidate.update(payload)
    assert_failure(candidate, "ACTION_FIELD_REQUIRED", "/payload")


class _HostMapping(Mapping[str, object]):
    def __iter__(self) -> object:
        return iter(())

    def __len__(self) -> int:
        return 0

    def __getitem__(self, key: str) -> object:
        raise KeyError(key)


class _HostSequence(Sequence[object]):
    def __getitem__(self, index: int) -> object:
        raise IndexError(index)

    def __len__(self) -> int:
        return 0


@pytest.mark.parametrize(
    "candidate",
    [
        b"not-json",
        float("nan"),
        float("inf"),
        float("-inf"),
        {1: "non-string-key"},
        _HostMapping(),
        _HostSequence(),
        object(),
    ],
)
def test_public_parser_rejects_non_json_domain_values(candidate: object) -> None:
    expected_path = "/*" if type(candidate) is dict else ""
    assert_failure(candidate, "ACTION_TYPE_INVALID", expected_path)


def test_public_parser_rejects_nested_non_json_domain_values_without_throwing() -> None:
    candidate = valid_actions()["search_literal"]
    payload = candidate["payload"]
    assert isinstance(payload, dict)
    payload["query"] = b"bytes"
    assert_failure(candidate, "ACTION_TYPE_INVALID", "/payload/query")


def test_all_eight_stable_codes_have_independent_public_mutations() -> None:
    malformed = valid_actions()["read_text"]
    relation_payload = malformed["payload"]
    assert isinstance(relation_payload, dict)
    relation_payload["start_line"] = 2
    relation_payload["end_line"] = 1
    mutations: list[tuple[object, str]] = [
        ([], "ACTION_SHAPE_INVALID"),
        (without(valid_actions()["list_directory"], ("action_id",)), "ACTION_FIELD_REQUIRED"),
        (mutate(valid_actions()["list_directory"], ("unexpected",), "x"), "ACTION_FIELD_UNKNOWN"),
        (mutate(valid_actions()["list_directory"], ("generation",), True), "ACTION_TYPE_INVALID"),
        (mutate(valid_actions()["list_directory"], ("payload", "max_depth"), 17), "ACTION_BOUND_INVALID"),
        (mutate(valid_actions()["apply_patch"], ("payload", "base_sha256"), "A" * 64), "ACTION_PATTERN_INVALID"),
        (mutate(valid_actions()["git_inspect"], ("payload", "operation"), "HEAD"), "ACTION_ENUM_INVALID"),
        (malformed, "ACTION_RELATION_INVALID"),
    ]
    observed: set[str] = set()
    for candidate, code in mutations:
        result = assert_failure(candidate, code)
        observed.update(issue.code for issue in result.issues)
    assert observed == ACTION_CODES


def _assert_owned_failure_anti_cheating_oracle(
    observed_codes: set[str], unknown_paths: tuple[str, ...], rendered: str, canary: str
) -> None:
    """Independent assertions that fail for the diagnostic shortcuts forbids."""

    assert observed_codes == ACTION_CODES
    assert unknown_paths == ("/*", "/payload/*", "/payload/arguments/*")
    assert canary not in rendered


def test_owned_failure_anti_cheating_oracle_rejects_each_contract_mutation() -> None:
    """Prove this test-owned oracle cannot pass after a weakened assertion."""

    canary = "candidate-value-input-prompt-provider-secret"
    safe_paths = ("/*", "/payload/*", "/payload/arguments/*")
    _assert_owned_failure_anti_cheating_oracle(set(ACTION_CODES), safe_paths, "safe", canary)
    for removed in ACTION_CODES:
        with pytest.raises(AssertionError):
            _assert_owned_failure_anti_cheating_oracle(
                set(ACTION_CODES) - {removed}, safe_paths, "safe", canary
            )
        with pytest.raises(AssertionError):
            _assert_owned_failure_anti_cheating_oracle(
                (set(ACTION_CODES) - {removed}) | {"ACTION_FUTURE_EXTENSION"},
                safe_paths,
                "safe",
                canary,
            )
    with pytest.raises(AssertionError):
        _assert_owned_failure_anti_cheating_oracle(
            set(ACTION_CODES),
            ("/*", "/payload/untrusted~1key", "/payload/arguments/*"),
            "safe",
            canary,
        )
    with pytest.raises(AssertionError):
        _assert_owned_failure_anti_cheating_oracle(
            set(ACTION_CODES), safe_paths, f"ValidationError: {canary}", canary
        )


def test_public_parser_keeps_unknown_keys_starred_and_rejects_enum_extensions() -> None:
    canary = "candidate-value-input-prompt-provider-secret"
    unknown_paths: list[str] = []
    rendered: list[str] = []
    for kind, path in (
        ("list_directory", (f"unknown-{canary}",)),
        ("list_directory", ("payload", f"unknown-{canary}")),
    ):
        candidate = valid_actions()[kind]
        if path[0] == "payload" and len(path) == 2:
            payload = candidate["payload"]
            assert isinstance(payload, dict)
            payload[path[1]] = canary
        else:
            candidate[path[0]] = canary
        result = assert_failure(candidate, "ACTION_FIELD_UNKNOWN")
        unknown_paths.extend(issue.path for issue in result.issues if issue.code == "ACTION_FIELD_UNKNOWN")
        rendered.extend((repr(result), str(result)))
    dynamic_result = assert_failure(
        mutate(
            valid_actions()["run_command"],
            ("payload", "arguments"),
            {f"unknown-{canary}\x00": "value"},
        ),
        "ACTION_PATTERN_INVALID",
        "/payload/arguments/*",
    )
    unknown_paths.append(dynamic_result.issues[0].path)
    rendered.extend((repr(dynamic_result), str(dynamic_result)))
    malformed = valid_actions()["read_text"]
    relation_payload = malformed["payload"]
    assert isinstance(relation_payload, dict)
    relation_payload.update({"start_line": 2, "end_line": 1})
    code_mutations: tuple[tuple[object, str], ...] = (
        ([], "ACTION_SHAPE_INVALID"),
        (without(valid_actions()["list_directory"], ("action_id",)), "ACTION_FIELD_REQUIRED"),
        (mutate(valid_actions()["list_directory"], ("unexpected",), "x"), "ACTION_FIELD_UNKNOWN"),
        (mutate(valid_actions()["list_directory"], ("generation",), True), "ACTION_TYPE_INVALID"),
        (mutate(valid_actions()["list_directory"], ("payload", "max_depth"), 17), "ACTION_BOUND_INVALID"),
        (mutate(valid_actions()["apply_patch"], ("payload", "base_sha256"), "A" * 64), "ACTION_PATTERN_INVALID"),
        (mutate(valid_actions()["git_inspect"], ("payload", "operation"), "HEAD"), "ACTION_ENUM_INVALID"),
        (malformed, "ACTION_RELATION_INVALID"),
    )
    observed_codes: set[str] = set()
    for malformed_candidate, code in code_mutations:
        result = assert_failure(malformed_candidate, code)
        observed_codes.update(issue.code for issue in result.issues)
    _assert_owned_failure_anti_cheating_oracle(
        observed_codes,
        tuple(unknown_paths),
        "\n".join(rendered),
        canary,
    )
    for kind, path, value in (
        ("list_directory", ("kind",), "future_action"),
        ("git_inspect", ("payload", "operation"), "future_operation"),
    ):
        assert_failure(mutate(valid_actions()[kind], path, value), "ACTION_ENUM_INVALID")


def test_issues_are_canonical_sorted_deduplicated_and_truncated() -> None:
    candidate = valid_actions()["apply_patch"]
    payload = candidate["payload"]
    assert isinstance(payload, dict)
    payload["hunks"] = [
        {
            "start_line": 1,
            "delete_line_count": 0,
            "expected_text": "",
            "replacement_text": "ok",
            f"bad_{index}": "ignored",
        }
        for index in range(40)
    ]
    result = assert_failure(candidate, "ACTION_FIELD_UNKNOWN")
    pairs = tuple((issue.path, issue.code) for issue in result.issues)
    assert pairs == tuple(sorted(set(pairs)))
    assert len(result.issues) == 32
    assert result.truncated is True
    assert all("bad_" not in issue.path for issue in result.issues)


def test_failure_does_not_leak_candidate_values_or_exception_details(caplog: pytest.LogCaptureFixture) -> None:
    canary = "candidate-value-input-prompt-provider-secret"
    candidate = valid_actions()["list_directory"]
    candidate[f"unknown-{canary}"] = canary
    caplog.set_level(logging.DEBUG)
    result = assert_failure(candidate, "ACTION_FIELD_UNKNOWN", "/*")
    assert canary not in repr(result)
    assert canary not in str(result)
    assert canary not in "\n".join(record.getMessage() for record in caplog.records)
    assert not hasattr(result, "__cause__")
    assert not hasattr(result, "__context__")


def test_success_and_failure_are_deeply_immutable_and_defensively_copied() -> None:
    candidate = valid_actions()["apply_patch"]
    result, failure_type, issue_type, success_type = parse(candidate)
    assert isinstance(result, success_type)
    before = result.action.model_dump(mode="json")
    payload = candidate["payload"]
    assert isinstance(payload, dict)
    hunks = payload["hunks"]
    assert isinstance(hunks, list) and isinstance(hunks[0], dict)
    hunks[0]["replacement_text"] = "attacker mutation"
    assert result.action.model_dump(mode="json") == before
    with pytest.raises(Exception):
        result.action.action_id = "changed"
    with pytest.raises(Exception):
        result.action.payload.hunks += ()
    with pytest.raises(Exception):
        result.action.payload.hunks[0].start_line = 2
    failure = assert_failure([], "ACTION_SHAPE_INVALID")
    assert isinstance(failure, failure_type)
    assert isinstance(failure.issues[0], issue_type)
    with pytest.raises(FrozenInstanceError):
        failure.reason_code = "changed"
    with pytest.raises(FrozenInstanceError):
        failure.issues[0].code = "changed"
    with pytest.raises(TypeError):
        failure.issues[0:1] = ()


def test_tuple_and_readonly_mapping_round_trip_as_json_arrays_and_objects() -> None:
    result, _failure_type, _issue_type, success_type = parse(valid_actions()["run_command"])
    assert isinstance(result, success_type)
    assert isinstance(result.action.payload.arguments, Mapping)
    with pytest.raises(TypeError):
        result.action.payload.arguments["new"] = "value"
    dumped = result.action.model_dump(mode="json")
    assert dumped["payload"]["arguments"] == {"target": "tests/unit"}
    assert isinstance(dumped["payload"]["arguments"], dict)


def test_parser_has_zero_runtime_filesystem_network_process_and_logging_side_effects(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[str] = []

    def forbidden(name: str) -> Callable[..., object]:
        def call(*args: object, **kwargs: object) -> object:
            calls.append(name)
            raise AssertionError(f"unexpected side effect: {name}")

        return call

    monkeypatch.setattr("builtins.open", forbidden("open"))
    monkeypatch.setattr(os, "open", forbidden("os.open"))
    monkeypatch.setattr(socket, "socket", forbidden("socket"))
    monkeypatch.setattr(socket, "create_connection", forbidden("create_connection"))
    monkeypatch.setattr(subprocess, "run", forbidden("subprocess"))
    monkeypatch.setattr(subprocess, "Popen", forbidden("Popen"))
    monkeypatch.setattr(logging.Logger, "_log", forbidden("logging"))
    caplog.set_level(logging.DEBUG)
    candidates = (valid_actions()["list_directory"], [])
    before = copy.deepcopy(candidates)
    success, _failure_type, _issue_type, success_type = parse(candidates[0])
    failure = assert_failure(candidates[1], "ACTION_SHAPE_INVALID")
    assert isinstance(success, success_type)
    assert failure.reason_code == "ACTION_CANDIDATE_INVALID"
    assert candidates == before
    assert calls == []
    assert caplog.records == []


def test_owned_parser_static_dependency_oracle_forbids_side_effect_modules() -> None:
    """A static test-owned oracle; it is deliberately not a public parser test."""

    parser_path = Path(__file__).parents[3] / "src/yagcode/domain/action_parser.py"
    tree = ast.parse(parser_path.read_text(encoding="utf-8"), filename=str(parser_path))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_roots.add(node.module.split(".", maxsplit=1)[0])
    forbidden_roots = {
        "policy",
        "persistence",
        "dispatcher",
        "tool",
        "git",
        "filesystem",
        "network",
        "logging",
    }
    assert imported_roots.isdisjoint(forbidden_roots)

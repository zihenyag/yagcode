"""Contract tests for public tool and validation result models.

The production module is deliberately loaded only through the runtime fixture.
That keeps the test-owned helper oracle executable during the RED phase.
"""

from __future__ import annotations

from copy import deepcopy
from importlib import import_module
from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError


@pytest.fixture
def tool_result_payload() -> dict[str, Any]:
    return {
        "action_id": "action-1",
        "status": "SUCCEEDED",
        "category": "command",
        "reason_code": "completed",
        "exit_code": None,
        "artifact_refs": [],
        "side_effect_state": "APPLIED",
        "retryable": False,
    }


@pytest.fixture
def validation_result_payload() -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "validator_id": "pytest",
        "required": True,
        "status": "PASS",
        "category": "test",
        "reason_code": "all-passed",
        "command_template_id": "unit-test",
        "exit_code": None,
        "summary": "All required tests passed.",
        "evidence_refs": [],
        "source_action_id": None,
        "retryable": False,
    }


@pytest.fixture
def load_results_contract() -> ModuleType:
    """Load the not-yet-existing production contract only when a test needs it."""

    return import_module("yagcode.domain.results")


def mutate_payload(payload: dict[str, Any], path: tuple[str | int, ...], value: Any) -> dict[str, Any]:
    """Deep-copy and replace exactly one existing dictionary key or list index."""

    if not path:
        raise AssertionError("mutation path must not be empty")

    copied = deepcopy(payload)
    target: Any = copied
    for segment in path[:-1]:
        if isinstance(target, dict) and type(segment) is str and segment in target:
            target = target[segment]
        elif isinstance(target, list) and type(segment) is int and 0 <= segment < len(target):
            target = target[segment]
        else:
            raise AssertionError(f"unsupported mutation path segment: {segment!r}")

    final_segment = path[-1]
    if isinstance(target, dict) and type(final_segment) is str and final_segment in target:
        target[final_segment] = value
    elif isinstance(target, list) and type(final_segment) is int and 0 <= final_segment < len(target):
        target[final_segment] = value
    else:
        raise AssertionError(f"unsupported final mutation path segment: {final_segment!r}")
    return copied


def test_owned_fixture_and_mutation_helpers(
    tool_result_payload: dict[str, Any], validation_result_payload: dict[str, Any]
) -> None:
    mutated = mutate_payload(tool_result_payload, ("action_id",), "replacement")
    assert mutated["action_id"] == "replacement"
    assert tool_result_payload["action_id"] == "action-1"

    nested = {"refs": ["original"]}
    nested_mutated = mutate_payload(nested, ("refs", 0), "replacement")
    assert nested_mutated == {"refs": ["replacement"]}
    assert nested == {"refs": ["original"]}

    assert validation_result_payload["run_id"] == "run-1"
    for invalid_path in ((), ("missing",), ("action_id", 0), ("refs", "0")):
        try:
            mutate_payload(nested, invalid_path, "replacement")
        except (KeyError, TypeError) as error:
            pytest.fail(f"mutation helper leaked {type(error).__name__}: {error}")
        except AssertionError:
            pass
        else:
            pytest.fail(f"invalid mutation path unexpectedly succeeded: {invalid_path!r}")


@pytest.mark.parametrize(
    "field",
    ("action_id", "status", "category", "reason_code", "side_effect_state", "retryable"),
)
def test_tool_result_rejects_each_required_field(
    load_results_contract: ModuleType, tool_result_payload: dict[str, Any], field: str
) -> None:
    payload = deepcopy(tool_result_payload)
    del payload[field]
    with pytest.raises(ValidationError):
        load_results_contract.ToolResult(**payload)


def test_tool_result_defaults_reject_extra_and_isolate_lists(
    load_results_contract: ModuleType, tool_result_payload: dict[str, Any]
) -> None:
    defaults_payload = deepcopy(tool_result_payload)
    del defaults_payload["exit_code"]
    del defaults_payload["artifact_refs"]
    first = load_results_contract.ToolResult(**defaults_payload)
    second = load_results_contract.ToolResult(**defaults_payload)
    assert first.exit_code is None
    assert first.artifact_refs == []
    assert first.artifact_refs is not second.artifact_refs
    first.artifact_refs.append("artifact-1")
    assert second.artifact_refs == []

    payload = deepcopy(tool_result_payload)
    payload["unexpected"] = "forbidden"
    with pytest.raises(ValidationError):
        load_results_contract.ToolResult(**payload)


def test_tool_status_and_side_effect_state_have_exact_members(
    load_results_contract: ModuleType,
) -> None:
    assert {member.value for member in load_results_contract.ToolStatus} == {
        "SUCCEEDED",
        "FAILED",
        "DENIED",
        "UNKNOWN",
    }
    assert len(load_results_contract.ToolStatus) == 4
    assert {member.value for member in load_results_contract.SideEffectState} == {
        "NONE",
        "APPLIED",
        "PARTIAL",
        "UNKNOWN",
    }
    assert len(load_results_contract.SideEffectState) == 4


@pytest.mark.parametrize("field", ("status", "side_effect_state"))
@pytest.mark.parametrize(
    "invalid_value",
    (
        "succeeded",
        "SUCCEEDED ",
        " SUCCEEDED",
        "success",
        "NOT_LISTED",
        None,
        1,
        True,
        [],
        {},
    ),
)
def test_tool_result_rejects_non_exact_enum_values(
    load_results_contract: ModuleType,
    tool_result_payload: dict[str, Any],
    field: str,
    invalid_value: Any,
) -> None:
    payload = mutate_payload(tool_result_payload, (field,), invalid_value)
    with pytest.raises(ValidationError):
        load_results_contract.ToolResult(**payload)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("exit_code", True),
        ("exit_code", 0.0),
        ("exit_code", "0"),
        ("retryable", 0),
        ("retryable", 1),
        ("retryable", "false"),
        ("retryable", None),
    ),
)
def test_tool_result_rejects_non_strict_scalars(
    load_results_contract: ModuleType,
    tool_result_payload: dict[str, Any],
    field: str,
    invalid_value: Any,
) -> None:
    payload = deepcopy(tool_result_payload)
    payload[field] = invalid_value
    with pytest.raises(ValidationError):
        load_results_contract.ToolResult(**payload)


@pytest.mark.parametrize(
    ("exit_code", "accepted"),
    (
        (-2_147_483_649, False),
        (-2_147_483_648, True),
        (2_147_483_647, True),
        (2_147_483_648, False),
    ),
)
def test_tool_result_enforces_exit_code_adjacent_bounds(
    load_results_contract: ModuleType,
    tool_result_payload: dict[str, Any],
    exit_code: int,
    accepted: bool,
) -> None:
    payload = deepcopy(tool_result_payload)
    payload["exit_code"] = exit_code
    if accepted:
        assert load_results_contract.ToolResult(**payload).exit_code == exit_code
    else:
        with pytest.raises(ValidationError):
            load_results_contract.ToolResult(**payload)


@pytest.mark.parametrize("field", ("action_id", "category", "reason_code"))
def test_tool_result_string_fields_enforce_adjacent_bounds(
    load_results_contract: ModuleType, tool_result_payload: dict[str, Any], field: str
) -> None:
    for value in ("x", "x" * 128):
        assert load_results_contract.ToolResult(**mutate_payload(tool_result_payload, (field,), value))
    for value in ("", "x" * 129):
        with pytest.raises(ValidationError):
            load_results_contract.ToolResult(**mutate_payload(tool_result_payload, (field,), value))


@pytest.mark.parametrize("field", ("action_id", "category", "reason_code"))
def test_tool_result_rejects_nul_in_string_fields(
    load_results_contract: ModuleType, tool_result_payload: dict[str, Any], field: str
) -> None:
    with pytest.raises(ValidationError):
        load_results_contract.ToolResult(
            **mutate_payload(tool_result_payload, (field,), "before\x00after")
        )


@pytest.mark.parametrize(
    "invalid_refs",
    (
        "artifact-1",
        ("artifact-1",),
        {"artifact-1"},
        {"artifact": "artifact-1"},
        ["artifact-1", 1],
        ["artifact-1", True],
        ["artifact-1", None],
        ["artifact-1", b"bytes"],
    ),
)
def test_tool_result_rejects_invalid_artifact_ref_containers_and_items(
    load_results_contract: ModuleType, tool_result_payload: dict[str, Any], invalid_refs: Any
) -> None:
    with pytest.raises(ValidationError):
        load_results_contract.ToolResult(**mutate_payload(tool_result_payload, ("artifact_refs",), invalid_refs))


@pytest.mark.parametrize(
    ("refs", "accepted"),
    (
        ([], True),
        (["x" * 1024], True),
        ([""], False),
        (["x" * 1025], False),
        (["x"] * 100, True),
        (["x"] * 101, False),
        (["before\x00after"], False),
    ),
)
def test_tool_result_enforces_artifact_ref_bounds_and_nul(
    load_results_contract: ModuleType,
    tool_result_payload: dict[str, Any],
    refs: list[str],
    accepted: bool,
) -> None:
    payload = mutate_payload(tool_result_payload, ("artifact_refs",), refs)
    if accepted:
        assert load_results_contract.ToolResult(**payload).artifact_refs == refs
    else:
        with pytest.raises(ValidationError):
            load_results_contract.ToolResult(**payload)


@pytest.mark.parametrize(
    "field",
    (
        "run_id",
        "validator_id",
        "required",
        "status",
        "category",
        "reason_code",
        "command_template_id",
        "summary",
        "retryable",
    ),
)
def test_validation_result_rejects_each_required_field(
    load_results_contract: ModuleType, validation_result_payload: dict[str, Any], field: str
) -> None:
    payload = deepcopy(validation_result_payload)
    del payload[field]
    with pytest.raises(ValidationError):
        load_results_contract.ValidationResult(**payload)


def test_validation_result_defaults_reject_extra_and_isolate_lists(
    load_results_contract: ModuleType, validation_result_payload: dict[str, Any]
) -> None:
    defaults_payload = deepcopy(validation_result_payload)
    del defaults_payload["exit_code"]
    del defaults_payload["evidence_refs"]
    del defaults_payload["source_action_id"]
    first = load_results_contract.ValidationResult(**defaults_payload)
    second = load_results_contract.ValidationResult(**defaults_payload)
    assert first.exit_code is None
    assert first.evidence_refs == []
    assert first.source_action_id is None
    assert first.evidence_refs is not second.evidence_refs
    first.evidence_refs.append("evidence-1")
    assert second.evidence_refs == []

    payload = deepcopy(validation_result_payload)
    payload["unexpected"] = "forbidden"
    with pytest.raises(ValidationError):
        load_results_contract.ValidationResult(**payload)


def test_validation_status_has_exact_members(load_results_contract: ModuleType) -> None:
    assert {member.value for member in load_results_contract.ValidationStatus} == {
        "PASS",
        "FAIL",
        "UNKNOWN",
        "MISSING",
    }
    assert len(load_results_contract.ValidationStatus) == 4


@pytest.mark.parametrize(
    "invalid_value",
    (
        "pass",
        "PASS ",
        " PASS",
        "SUCCESS",
        "NOT_LISTED",
        None,
        1,
        True,
        [],
        {},
    ),
)
def test_validation_result_rejects_non_exact_status_values(
    load_results_contract: ModuleType,
    validation_result_payload: dict[str, Any],
    invalid_value: Any,
) -> None:
    with pytest.raises(ValidationError):
        load_results_contract.ValidationResult(
            **mutate_payload(validation_result_payload, ("status",), invalid_value)
        )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("exit_code", True),
        ("exit_code", 0.0),
        ("exit_code", "0"),
        ("required", 0),
        ("required", 1),
        ("required", "true"),
        ("retryable", 0),
        ("retryable", 1),
        ("retryable", "false"),
        ("retryable", None),
    ),
)
def test_validation_result_rejects_non_strict_scalars(
    load_results_contract: ModuleType,
    validation_result_payload: dict[str, Any],
    field: str,
    invalid_value: Any,
) -> None:
    payload = deepcopy(validation_result_payload)
    payload[field] = invalid_value
    with pytest.raises(ValidationError):
        load_results_contract.ValidationResult(**payload)


@pytest.mark.parametrize(
    ("exit_code", "accepted"),
    (
        (-2_147_483_649, False),
        (-2_147_483_648, True),
        (2_147_483_647, True),
        (2_147_483_648, False),
    ),
)
def test_validation_result_enforces_exit_code_adjacent_bounds(
    load_results_contract: ModuleType,
    validation_result_payload: dict[str, Any],
    exit_code: int,
    accepted: bool,
) -> None:
    payload = deepcopy(validation_result_payload)
    payload["exit_code"] = exit_code
    if accepted:
        assert load_results_contract.ValidationResult(**payload).exit_code == exit_code
    else:
        with pytest.raises(ValidationError):
            load_results_contract.ValidationResult(**payload)


@pytest.mark.parametrize(
    ("field", "minimum", "maximum"),
    (
        ("run_id", 1, 128),
        ("validator_id", 1, 128),
        ("category", 1, 128),
        ("reason_code", 1, 128),
        ("command_template_id", 1, 128),
        ("summary", 1, 4000),
        ("source_action_id", 1, 128),
    ),
)
def test_validation_result_string_fields_enforce_adjacent_bounds(
    load_results_contract: ModuleType,
    validation_result_payload: dict[str, Any],
    field: str,
    minimum: int,
    maximum: int,
) -> None:
    for value in ("x" * minimum, "x" * maximum):
        assert load_results_contract.ValidationResult(
            **mutate_payload(validation_result_payload, (field,), value)
        )
    for value in ("x" * (minimum - 1), "x" * (maximum + 1)):
        with pytest.raises(ValidationError):
            load_results_contract.ValidationResult(
                **mutate_payload(validation_result_payload, (field,), value)
            )


@pytest.mark.parametrize(
    "field",
    (
        "run_id",
        "validator_id",
        "category",
        "reason_code",
        "command_template_id",
        "summary",
        "source_action_id",
    ),
)
def test_validation_result_rejects_nul_in_string_fields(
    load_results_contract: ModuleType, validation_result_payload: dict[str, Any], field: str
) -> None:
    with pytest.raises(ValidationError):
        load_results_contract.ValidationResult(
            **mutate_payload(validation_result_payload, (field,), "before\x00after")
        )


@pytest.mark.parametrize(
    "invalid_refs",
    (
        "evidence-1",
        ("evidence-1",),
        {"evidence-1"},
        {"evidence": "evidence-1"},
        ["evidence-1", 1],
        ["evidence-1", True],
        ["evidence-1", None],
        ["evidence-1", b"bytes"],
    ),
)
def test_validation_result_rejects_invalid_evidence_ref_containers_and_items(
    load_results_contract: ModuleType, validation_result_payload: dict[str, Any], invalid_refs: Any
) -> None:
    with pytest.raises(ValidationError):
        load_results_contract.ValidationResult(
            **mutate_payload(validation_result_payload, ("evidence_refs",), invalid_refs)
        )


@pytest.mark.parametrize(
    ("refs", "accepted"),
    (
        ([], True),
        (["x" * 1024], True),
        ([""], False),
        (["x" * 1025], False),
        (["x"] * 100, True),
        (["x"] * 101, False),
        (["before\x00after"], False),
    ),
)
def test_validation_result_enforces_evidence_ref_bounds_and_nul(
    load_results_contract: ModuleType,
    validation_result_payload: dict[str, Any],
    refs: list[str],
    accepted: bool,
) -> None:
    payload = mutate_payload(validation_result_payload, ("evidence_refs",), refs)
    if accepted:
        assert load_results_contract.ValidationResult(**payload).evidence_refs == refs
    else:
        with pytest.raises(ValidationError):
            load_results_contract.ValidationResult(**payload)

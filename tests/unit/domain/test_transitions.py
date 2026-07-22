"""Test-owned contract for the four pure lifecycle transition functions."""

from __future__ import annotations

import ast
import copy
import importlib
import inspect
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

import pytest


RUN_STATES = {
    "CREATED",
    "PLANNING",
    "WAITING_PLAN_APPROVAL",
    "RUNNING",
    "WAITING_PERMISSION",
    "WAITING_PRIVACY",
    "COMPACTING",
    "STOPPING",
    "PAUSED_BY_USER",
    "PAUSED_BUDGET",
    "PAUSED_FAILURE",
    "INTERRUPTED",
    "FINISHED",
}
TASK_STATES = {"DRAFT", "ACTIVE", "CLOSED", "ARCHIVED"}
REVIEW_STATES = {
    "NOT_READY",
    "INCOMPLETE",
    "READY",
    "ACCEPTING",
    "ACCEPTED",
    "REJECTED",
    "CONFLICT",
    "RECOVERY_REQUIRED",
}
INTEGRATION_STATES = {
    "PREPARING",
    "PREPARED",
    "APPLYING",
    "VERIFYING",
    "ACCEPTED",
    "CONFLICT_BEFORE_WRITE",
    "COMPENSATING",
    "ACCEPT_FAILED_ROLLED_BACK",
    "ACCEPT_RECOVERY_REQUIRED",
}
RECOVERY_CLASSES = {
    "ALL_PREIMAGE",
    "OWNED_POSTIMAGE_COMPENSATABLE",
    "ALL_POSTIMAGE",
    "MIXED_OR_UNKNOWN",
}

RUN_EVENTS = (
    "start_plan",
    "start_without_plan",
    "plan_ready",
    "approve_plan",
    "wait_permission",
    "wait_privacy",
    "decision_resolved",
    "start_compaction",
    "compaction_succeeded",
    "compaction_failed",
    "request_stop",
    "stop_confirmed",
    "stop_unconfirmed",
    "pause_budget",
    "pause_failure",
    "resume",
    "switch_model",
    "finish_candidate",
)
TASK_EVENTS = ("activate", "close", "reopen", "archive", "restore_archive")
REVIEW_EVENTS = (
    "candidate_incomplete",
    "candidate_ready",
    "continue_work",
    "begin_accept",
    "accept_succeeded",
    "accept_conflict",
    "accept_recovery_required",
    "accept_rolled_back",
    "resolve_conflict_ready",
    "resolve_conflict_incomplete",
    "reject",
    "recovery_still_required",
)
INTEGRATION_EVENTS = (
    "prepare_succeeded",
    "conflict_before_write",
    "begin_apply",
    "apply_succeeded",
    "apply_failed",
    "verification_succeeded",
    "verification_failed",
    "compensation_succeeded",
    "compensation_failed",
    "recover",
    "resolve_recovery_rolled_back",
    "confirm_recovered_acceptance",
)


@dataclass(frozen=True)
class Case:
    state: str
    event: str
    guards: dict[str, Any]
    target: str


def _g(**kwargs: Any) -> dict[str, Any]:
    return kwargs


# These rows are deliberately handwritten test data, not a copy of a production table.
RUN_SUCCESS = (
    Case("CREATED", "start_plan", _g(project_lock_acquired=True), "PLANNING"),
    Case(
        "CREATED",
        "start_without_plan",
        _g(project_lock_acquired=True, start_checkpoint_persisted=True),
        "RUNNING",
    ),
    Case("PLANNING", "plan_ready", _g(), "WAITING_PLAN_APPROVAL"),
    Case("WAITING_PLAN_APPROVAL", "approve_plan", _g(plan_approved=True), "RUNNING"),
    Case("RUNNING", "wait_permission", _g(), "WAITING_PERMISSION"),
    Case("RUNNING", "wait_privacy", _g(), "WAITING_PRIVACY"),
    Case("WAITING_PERMISSION", "decision_resolved", _g(), "RUNNING"),
    Case("WAITING_PRIVACY", "decision_resolved", _g(), "RUNNING"),
    Case("RUNNING", "start_compaction", _g(), "COMPACTING"),
    Case("COMPACTING", "compaction_succeeded", _g(), "RUNNING"),
    Case("COMPACTING", "compaction_failed", _g(), "PAUSED_FAILURE"),
    *(
        Case(state, "request_stop", _g(), "STOPPING")
        for state in (
            "PLANNING",
            "WAITING_PLAN_APPROVAL",
            "RUNNING",
            "WAITING_PERMISSION",
            "WAITING_PRIVACY",
            "COMPACTING",
            "STOPPING",
        )
    ),
    Case(
        "STOPPING",
        "stop_confirmed",
        _g(process_tree_dead=True, stop_checkpoint_persisted=True),
        "PAUSED_BY_USER",
    ),
    Case(
        "INTERRUPTED",
        "stop_confirmed",
        _g(
            process_tree_dead=True,
            stop_checkpoint_persisted=True,
            unknown_side_effects_reconciled=True,
        ),
        "PAUSED_BY_USER",
    ),
    Case("STOPPING", "stop_unconfirmed", _g(), "INTERRUPTED"),
    Case("RUNNING", "pause_budget", _g(), "PAUSED_BUDGET"),
    Case("RUNNING", "pause_failure", _g(), "PAUSED_FAILURE"),
    *(
        Case(state, "resume", _g(resume_guards_resolved=True), "RUNNING")
        for state in (
            "PAUSED_BY_USER",
            "PAUSED_BUDGET",
            "PAUSED_FAILURE",
        )
    ),
    Case("PAUSED_BY_USER", "switch_model", _g(), "PAUSED_BY_USER"),
    Case("RUNNING", "finish_candidate", _g(pending_side_effects=False), "FINISHED"),
)
TASK_SUCCESS = (
    Case("DRAFT", "activate", _g(project_lock_acquired=True), "ACTIVE"),
    Case(
        "ACTIVE",
        "close",
        _g(has_locking_run=False, has_pending_approval=False, review_state="READY"),
        "CLOSED",
    ),
    Case("CLOSED", "reopen", _g(), "ACTIVE"),
    Case(
        "CLOSED",
        "archive",
        _g(has_locking_run=False, has_pending_approval=False, review_state="READY"),
        "ARCHIVED",
    ),
    Case("ARCHIVED", "restore_archive", _g(), "CLOSED"),
)
REVIEW_SUCCESS = (
    *(
        Case(
            state,
            "candidate_incomplete",
            _g(validations_evaluated=True, required_validations_passed=False),
            "INCOMPLETE",
        )
        for state in ("NOT_READY", "READY")
    ),
    *(
        Case(
            state,
            "candidate_ready",
            _g(validations_evaluated=True, required_validations_passed=True),
            "READY",
        )
        for state in ("NOT_READY", "INCOMPLETE")
    ),
    *(Case(state, "continue_work", _g(), "NOT_READY") for state in ("READY", "INCOMPLETE")),
    Case(
        "READY",
        "begin_accept",
        _g(no_hard_block=True, no_unknown_side_effect=True, no_live_process=True),
        "ACCEPTING",
    ),
    Case(
        "INCOMPLETE",
        "begin_accept",
        _g(
            no_hard_block=True,
            no_unknown_side_effect=True,
            no_live_process=True,
            incomplete_confirmation=True,
        ),
        "ACCEPTING",
    ),
    *(
        Case(
            state,
            "accept_succeeded",
            _g(integration_outcome="ACCEPTED", trusted_confirmation=state == "RECOVERY_REQUIRED"),
            "ACCEPTED",
        )
        for state in ("ACCEPTING", "RECOVERY_REQUIRED")
    ),
    Case(
        "ACCEPTING", "accept_conflict", _g(integration_outcome="CONFLICT_BEFORE_WRITE"), "CONFLICT"
    ),
    Case(
        "ACCEPTING",
        "accept_recovery_required",
        _g(integration_outcome="ACCEPT_RECOVERY_REQUIRED"),
        "RECOVERY_REQUIRED",
    ),
    *(
        Case(
            state,
            "accept_rolled_back",
            _g(
                integration_outcome="ACCEPT_FAILED_ROLLED_BACK",
                preimage_verified=True,
                prior_review_state=prior,
            ),
            prior,
        )
        for state in ("ACCEPTING", "RECOVERY_REQUIRED")
        for prior in ("READY", "INCOMPLETE")
    ),
    Case(
        "CONFLICT",
        "resolve_conflict_ready",
        _g(conflict_cleared=True, validations_evaluated=True, required_validations_passed=True),
        "READY",
    ),
    Case(
        "CONFLICT",
        "resolve_conflict_incomplete",
        _g(conflict_cleared=True, validations_evaluated=True, required_validations_passed=False),
        "INCOMPLETE",
    ),
    *(
        Case(
            state,
            "reject",
            _g(no_hard_block=True, no_unknown_side_effect=True, no_live_process=True),
            "REJECTED",
        )
        for state in ("NOT_READY", "INCOMPLETE", "READY", "CONFLICT")
    ),
    Case(
        "RECOVERY_REQUIRED",
        "recovery_still_required",
        _g(integration_outcome="ACCEPT_RECOVERY_REQUIRED"),
        "RECOVERY_REQUIRED",
    ),
)
INTEGRATION_SUCCESS = (
    Case(
        "PREPARING", "prepare_succeeded", _g(manifest_persisted=True, locks_held=True), "PREPARED"
    ),
    *(
        Case(state, "conflict_before_write", _g(no_real_write=True), "CONFLICT_BEFORE_WRITE")
        for state in ("PREPARING", "PREPARED")
    ),
    Case("PREPARED", "begin_apply", _g(manifest_persisted=True, locks_held=True), "APPLYING"),
    Case("APPLYING", "apply_succeeded", _g(all_entries_applied=True), "VERIFYING"),
    Case("APPLYING", "apply_failed", _g(failure_recorded=True), "COMPENSATING"),
    Case(
        "VERIFYING",
        "verification_succeeded",
        _g(all_entries_verified=True, required_validations_passed=True),
        "ACCEPTED",
    ),
    Case("VERIFYING", "verification_failed", _g(failure_recorded=True), "COMPENSATING"),
    Case(
        "COMPENSATING",
        "compensation_succeeded",
        _g(all_preimages_verified=True),
        "ACCEPT_FAILED_ROLLED_BACK",
    ),
    Case(
        "COMPENSATING",
        "compensation_failed",
        _g(recovery_evidence_recorded=True),
        "ACCEPT_RECOVERY_REQUIRED",
    ),
    *(
        Case(
            state,
            "recover",
            _g(
                recovery_evidence_recorded=True,
                recovery_classification=klass,
                all_preimages_verified=klass == "ALL_PREIMAGE",
            ),
            {
                "ALL_PREIMAGE": "ACCEPT_FAILED_ROLLED_BACK",
                "OWNED_POSTIMAGE_COMPENSATABLE": "COMPENSATING",
                "ALL_POSTIMAGE": "ACCEPT_RECOVERY_REQUIRED",
                "MIXED_OR_UNKNOWN": "ACCEPT_RECOVERY_REQUIRED",
            }[klass],
        )
        for state in ("PREPARED", "APPLYING", "VERIFYING", "COMPENSATING")
        for klass in (
            "ALL_PREIMAGE",
            "OWNED_POSTIMAGE_COMPENSATABLE",
            "ALL_POSTIMAGE",
            "MIXED_OR_UNKNOWN",
        )
    ),
    Case(
        "ACCEPT_RECOVERY_REQUIRED",
        "resolve_recovery_rolled_back",
        _g(recovery_classification="ALL_PREIMAGE", all_preimages_verified=True),
        "ACCEPT_FAILED_ROLLED_BACK",
    ),
    Case(
        "ACCEPT_RECOVERY_REQUIRED",
        "confirm_recovered_acceptance",
        _g(
            recovery_classification="ALL_POSTIMAGE",
            all_entries_verified=True,
            required_validations_passed=True,
            trusted_confirmation=True,
        ),
        "ACCEPTED",
    ),
)

ALLOWED = {
    "run": {
        event: {case.state for case in RUN_SUCCESS if case.event == event} for event in RUN_EVENTS
    },
    "task": {
        event: {case.state for case in TASK_SUCCESS if case.event == event} for event in TASK_EVENTS
    },
    "review": {
        event: {case.state for case in REVIEW_SUCCESS if case.event == event}
        for event in REVIEW_EVENTS
    },
    "integration": {
        event: {case.state for case in INTEGRATION_SUCCESS if case.event == event}
        for event in INTEGRATION_EVENTS
    },
}


def test_owned_matrix_cardinalities() -> None:
    assert (len(RUN_SUCCESS), len(TASK_SUCCESS), len(REVIEW_SUCCESS), len(INTEGRATION_SUCCESS)) == (
        28,
        5,
        23,
        28,
    )
    assert sum(map(len, (RUN_SUCCESS, TASK_SUCCESS, REVIEW_SUCCESS, INTEGRATION_SUCCESS))) == 84
    assert (len(RUN_EVENTS), len(TASK_EVENTS), len(REVIEW_EVENTS), len(INTEGRATION_EVENTS)) == (
        18,
        5,
        12,
        12,
    )
    assert (
        sum((len(RUN_EVENTS), len(TASK_EVENTS), len(REVIEW_EVENTS), len(INTEGRATION_EVENTS))) == 47
    )


def test_owned_every_event_has_a_success_row() -> None:
    for name, events, cases in (
        ("run", RUN_EVENTS, RUN_SUCCESS),
        ("task", TASK_EVENTS, TASK_SUCCESS),
        ("review", REVIEW_EVENTS, REVIEW_SUCCESS),
        ("integration", INTEGRATION_EVENTS, INTEGRATION_SUCCESS),
    ):
        assert {case.event for case in cases} == set(events), name


class FakeTransitionError(Exception):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code


def assert_transition_case(
    transition: Callable[[Any, Any, Any], Any],
    state: Any,
    event: Any,
    guards: Any,
    *,
    target: Any | None = None,
    reason_code: str | None = None,
) -> None:
    before = copy.deepcopy((state, event, guards))

    def unchanged() -> bool:
        def same(left: Any, right: Any) -> bool:
            if type(left) is object and type(right) is object:
                return True
            return left == right

        return all(
            same(left, right) for left, right in zip((state, event, guards), before, strict=True)
        )

    try:
        result = transition(state, event, guards)
    except Exception as exc:
        assert unchanged()
        if reason_code is None:
            raise
        assert getattr(exc, "reason_code", None) == reason_code
        return
    assert unchanged()
    assert reason_code is None
    assert result == target


def test_owned_input_helper_success_sentinel() -> None:
    state, event, guards = ["state"], ["event"], {"ok": True}
    assert_transition_case(lambda a, b, c: "target", state, event, guards, target="target")
    assert (state, event, guards) == (["state"], ["event"], {"ok": True})


def test_owned_input_helper_failure_sentinel_preserves_reason_code() -> None:
    def fail(_: Any, __: Any, ___: Any) -> Any:
        raise FakeTransitionError("SENTINEL")

    assert_transition_case(fail, "state", "event", {"ok": True}, reason_code="SENTINEL")


def test_owned_input_helper_detects_mutation() -> None:
    def mutate(_: Any, __: Any, guards: dict[str, Any]) -> Any:
        guards["changed"] = True
        return "ignored"

    with pytest.raises(AssertionError):
        assert_transition_case(mutate, "state", "event", {"ok": True}, target="ignored")


@dataclass
class _MutationSentinel:
    value: str = "before"


def test_owned_input_helper_detects_attribute_mutation() -> None:
    sentinel = _MutationSentinel()

    def mutate(_: Any, __: Any, guards: _MutationSentinel) -> Any:
        guards.value = "after"
        return "ignored"

    with pytest.raises(AssertionError):
        assert_transition_case(mutate, "state", "event", sentinel, target="ignored")


def test_owned_ast_forbids_direct_transition_calls_outside_helper() -> None:
    tree = ast.parse(Path(__file__).read_text())
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    prohibited = {
        "transition_run",
        "transition_task",
        "transition_review",
        "transition_integration",
    }
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Call)
            or not isinstance(node.func, ast.Name)
            or node.func.id not in prohibited
        ):
            continue
        current: ast.AST | None = node
        in_helper = False
        while current is not None:
            if (
                isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef))
                and current.name == "assert_transition_case"
            ):
                in_helper = True
                break
            current = parent.get(current)
        assert in_helper, f"{node.func.id} must be invoked only through assert_transition_case"


@dataclass(frozen=True)
class Contract:
    state_types: dict[str, type[StrEnum]]
    event_types: dict[str, type[StrEnum]]
    guard_types: dict[str, type[Any]]
    transitions: dict[str, Callable[[Any, Any, Any], Any]]
    transition_error: type[Exception]
    recovery_class: type[StrEnum]


def load_transition_contract() -> Contract:
    states = importlib.import_module("yagcode.domain.states")
    errors = importlib.import_module("yagcode.domain.errors")
    transitions = importlib.import_module("yagcode.domain.transitions")
    return Contract(
        state_types={
            "run": states.RunState,
            "task": states.TaskState,
            "review": states.ReviewState,
            "integration": states.IntegrationState,
        },
        event_types={
            "run": states.RunEvent,
            "task": states.TaskEvent,
            "review": states.ReviewEvent,
            "integration": states.IntegrationEvent,
        },
        guard_types={
            "run": transitions.RunGuards,
            "task": transitions.TaskGuards,
            "review": transitions.ReviewGuards,
            "integration": transitions.IntegrationGuards,
        },
        transitions={
            "run": transitions.transition_run,
            "task": transitions.transition_task,
            "review": transitions.transition_review,
            "integration": transitions.transition_integration,
        },
        transition_error=errors.TransitionError,
        recovery_class=states.RecoveryClass,
    )


@pytest.fixture(scope="module")
def contract() -> Contract:
    return load_transition_contract()


def _convert_guard(contract: Contract, machine: str, values: dict[str, Any]) -> Any:
    data = dict(values)
    if machine == "task" and isinstance(data.get("review_state"), str):
        data["review_state"] = contract.state_types["review"][data["review_state"]]
    if machine == "review":
        for field in ("integration_outcome",):
            if isinstance(data.get(field), str):
                data[field] = contract.state_types["integration"][data[field]]
        if isinstance(data.get("prior_review_state"), str):
            data["prior_review_state"] = contract.state_types["review"][data["prior_review_state"]]
    if machine == "integration" and isinstance(data.get("recovery_classification"), str):
        data["recovery_classification"] = contract.recovery_class[data["recovery_classification"]]
    return contract.guard_types[machine](**data)


def _assert_case(contract: Contract, machine: str, case: Case, *, raw: bool = False) -> None:
    assert_transition_case(
        contract.transitions[machine],
        contract.state_types[machine][case.state],
        case.event if raw else contract.event_types[machine](case.event),
        _convert_guard(contract, machine, case.guards),
        target=contract.state_types[machine][case.target],
    )


@pytest.mark.parametrize(
    ("machine", "case"),
    [("run", case) for case in RUN_SUCCESS]
    + [("task", case) for case in TASK_SUCCESS]
    + [("review", case) for case in REVIEW_SUCCESS]
    + [("integration", case) for case in INTEGRATION_SUCCESS],
    ids=lambda item: getattr(item, "event", item),
)
def test_enum_success_rows(contract: Contract, machine: str, case: Case) -> None:
    _assert_case(contract, machine, case)


@pytest.mark.parametrize(
    ("machine", "case"),
    [("run", next(case for case in RUN_SUCCESS if case.event == event)) for event in RUN_EVENTS]
    + [
        ("task", next(case for case in TASK_SUCCESS if case.event == event))
        for event in TASK_EVENTS
    ]
    + [
        ("review", next(case for case in REVIEW_SUCCESS if case.event == event))
        for event in REVIEW_EVENTS
    ]
    + [
        ("integration", next(case for case in INTEGRATION_SUCCESS if case.event == event))
        for event in INTEGRATION_EVENTS
    ],
    ids=lambda item: getattr(item, "event", item),
)
def test_raw_string_success_rows(contract: Contract, machine: str, case: Case) -> None:
    _assert_case(contract, machine, case, raw=True)


@pytest.mark.parametrize(
    ("machine", "expected_states", "expected_events"),
    [
        ("run", RUN_STATES, set(RUN_EVENTS)),
        ("task", TASK_STATES, set(TASK_EVENTS)),
        ("review", REVIEW_STATES, set(REVIEW_EVENTS)),
        ("integration", INTEGRATION_STATES, set(INTEGRATION_EVENTS)),
    ],
)
def test_exact_state_and_event_sets(
    contract: Contract, machine: str, expected_states: set[str], expected_events: set[str]
) -> None:
    assert issubclass(contract.state_types[machine], StrEnum)
    assert issubclass(contract.event_types[machine], StrEnum)
    assert {member.value for member in contract.state_types[machine]} == expected_states
    assert {member.value for member in contract.event_types[machine]} == expected_events


def test_exact_recovery_class_set(contract: Contract) -> None:
    assert issubclass(contract.recovery_class, StrEnum)
    assert {member.value for member in contract.recovery_class} == RECOVERY_CLASSES


def _invalid_reason(machine: str, event: str, state: str) -> str:
    if machine == "run":
        if event == "decision_resolved":
            return "RUN_DECISION_NOT_PENDING"
        if event == "request_stop":
            return "RUN_RECONCILIATION_REQUIRED" if state == "INTERRUPTED" else "RUN_NOT_ACTIVE"
        if event in {"stop_confirmed", "stop_unconfirmed"}:
            return "RUN_STOP_NOT_PENDING"
        if event == "resume":
            return "RUN_RESUME_GUARD_UNMET"
        if event == "switch_model":
            return "MODEL_SWITCH_REQUIRES_PAUSED_BY_USER"
    return f"{machine.upper()}_TRANSITION_INVALID"


def _invalid_state_cases(
    machine: str, states: set[str], events: tuple[str, ...]
) -> list[tuple[str, str, str]]:
    return [
        (state, event, _invalid_reason(machine, event, state))
        for event in events
        for state in sorted(states - ALLOWED[machine][event])
    ]


@pytest.mark.parametrize(
    ("machine", "state", "event", "reason"),
    [("run", *row) for row in _invalid_state_cases("run", RUN_STATES, RUN_EVENTS)]
    + [("task", *row) for row in _invalid_state_cases("task", TASK_STATES, TASK_EVENTS)]
    + [("review", *row) for row in _invalid_state_cases("review", REVIEW_STATES, REVIEW_EVENTS)]
    + [
        ("integration", *row)
        for row in _invalid_state_cases("integration", INTEGRATION_STATES, INTEGRATION_EVENTS)
    ],
)
def test_invalid_prior_state_complements(
    contract: Contract, machine: str, state: str, event: str, reason: str
) -> None:
    assert_transition_case(
        contract.transitions[machine],
        contract.state_types[machine][state],
        contract.event_types[machine](event),
        _convert_guard(contract, machine, {}),
        reason_code=reason,
    )


GUARD_FAILURES = (
    ("run", "CREATED", "start_plan", {}, "RUN_START_REQUIRES_PROJECT_LOCK"),
    ("run", "CREATED", "start_without_plan", {}, "RUN_START_REQUIRES_PROJECT_LOCK"),
    (
        "run",
        "CREATED",
        "start_without_plan",
        _g(project_lock_acquired=True),
        "RUN_START_CHECKPOINT_REQUIRED",
    ),
    ("run", "WAITING_PLAN_APPROVAL", "approve_plan", {}, "PLAN_APPROVAL_REQUIRED"),
    ("run", "STOPPING", "stop_confirmed", {}, "RUN_STOP_PROCESS_STILL_ALIVE"),
    (
        "run",
        "STOPPING",
        "stop_confirmed",
        _g(process_tree_dead=True),
        "RUN_STOP_CHECKPOINT_REQUIRED",
    ),
    (
        "run",
        "INTERRUPTED",
        "stop_confirmed",
        _g(process_tree_dead=True, stop_checkpoint_persisted=True),
        "RUN_RECONCILIATION_REQUIRED",
    ),
    ("run", "PAUSED_BY_USER", "resume", {}, "RUN_RESUME_GUARD_UNMET"),
    ("run", "RUNNING", "finish_candidate", {}, "RUN_PENDING_SIDE_EFFECTS"),
    ("task", "DRAFT", "activate", {}, "TASK_ACTIVATION_REQUIRES_PROJECT_LOCK"),
    *(
        ("task", state, event, guards, reason)
        for state, event in (("ACTIVE", "close"), ("CLOSED", "archive"))
        for guards, reason in (
            ({}, "TASK_CLOSE_BLOCKED_BY_RUN"),
            (_g(has_locking_run=False), "TASK_CLOSE_BLOCKED_BY_APPROVAL"),
            (_g(has_locking_run=False, has_pending_approval=False), "TASK_REVIEW_STATE_REQUIRED"),
            (
                _g(has_locking_run=False, has_pending_approval=False, review_state="ACCEPTING"),
                "TASK_CLOSE_BLOCKED_BY_ACCEPTING",
            ),
            (
                _g(
                    has_locking_run=False,
                    has_pending_approval=False,
                    review_state="RECOVERY_REQUIRED",
                ),
                "TASK_CLOSE_BLOCKED_BY_RECOVERY",
            ),
        )
    ),
    ("review", "NOT_READY", "candidate_incomplete", {}, "REVIEW_VALIDATIONS_NOT_EVALUATED"),
    (
        "review",
        "NOT_READY",
        "candidate_incomplete",
        _g(validations_evaluated=True, required_validations_passed=True),
        "REVIEW_VALIDATION_PROJECTION_MISMATCH",
    ),
    ("review", "NOT_READY", "candidate_ready", {}, "REVIEW_VALIDATIONS_NOT_EVALUATED"),
    (
        "review",
        "NOT_READY",
        "candidate_ready",
        _g(validations_evaluated=True),
        "REVIEW_REQUIRED_VALIDATIONS_NOT_PASSED",
    ),
    ("review", "READY", "begin_accept", {}, "REVIEW_HARD_BLOCK_UNRESOLVED"),
    ("review", "READY", "begin_accept", _g(no_hard_block=True), "REVIEW_UNKNOWN_SIDE_EFFECTS"),
    (
        "review",
        "READY",
        "begin_accept",
        _g(no_hard_block=True, no_unknown_side_effect=True),
        "REVIEW_PROCESS_STILL_RUNNING",
    ),
    (
        "review",
        "INCOMPLETE",
        "begin_accept",
        _g(no_hard_block=True, no_unknown_side_effect=True, no_live_process=True),
        "REVIEW_INCOMPLETE_CONFIRMATION_REQUIRED",
    ),
    ("review", "ACCEPTING", "accept_succeeded", {}, "REVIEW_INTEGRATION_OUTCOME_MISMATCH"),
    (
        "review",
        "RECOVERY_REQUIRED",
        "accept_succeeded",
        _g(integration_outcome="ACCEPTED"),
        "REVIEW_TRUSTED_CONFIRMATION_REQUIRED",
    ),
    ("review", "ACCEPTING", "accept_conflict", {}, "REVIEW_INTEGRATION_OUTCOME_MISMATCH"),
    (
        "review",
        "ACCEPTING",
        "accept_recovery_required",
        {},
        "REVIEW_INTEGRATION_OUTCOME_MISMATCH",
    ),
    ("review", "ACCEPTING", "accept_rolled_back", {}, "REVIEW_INTEGRATION_OUTCOME_MISMATCH"),
    (
        "review",
        "ACCEPTING",
        "accept_rolled_back",
        _g(integration_outcome="ACCEPT_FAILED_ROLLED_BACK"),
        "REVIEW_ROLLBACK_NOT_VERIFIED",
    ),
    (
        "review",
        "ACCEPTING",
        "accept_rolled_back",
        _g(integration_outcome="ACCEPT_FAILED_ROLLED_BACK", preimage_verified=True),
        "REVIEW_PRIOR_STATE_REQUIRED",
    ),
    ("review", "CONFLICT", "resolve_conflict_ready", {}, "REVIEW_CONFLICT_NOT_RESOLVED"),
    (
        "review",
        "CONFLICT",
        "resolve_conflict_ready",
        _g(conflict_cleared=True),
        "REVIEW_VALIDATIONS_NOT_EVALUATED",
    ),
    (
        "review",
        "CONFLICT",
        "resolve_conflict_ready",
        _g(conflict_cleared=True, validations_evaluated=True),
        "REVIEW_VALIDATION_PROJECTION_MISMATCH",
    ),
    ("review", "CONFLICT", "resolve_conflict_incomplete", {}, "REVIEW_CONFLICT_NOT_RESOLVED"),
    (
        "review",
        "CONFLICT",
        "resolve_conflict_incomplete",
        _g(conflict_cleared=True),
        "REVIEW_VALIDATIONS_NOT_EVALUATED",
    ),
    (
        "review",
        "CONFLICT",
        "resolve_conflict_incomplete",
        _g(conflict_cleared=True, validations_evaluated=True, required_validations_passed=True),
        "REVIEW_VALIDATION_PROJECTION_MISMATCH",
    ),
    ("review", "READY", "reject", {}, "REVIEW_HARD_BLOCK_UNRESOLVED"),
    ("review", "READY", "reject", _g(no_hard_block=True), "REVIEW_UNKNOWN_SIDE_EFFECTS"),
    (
        "review",
        "READY",
        "reject",
        _g(no_hard_block=True, no_unknown_side_effect=True),
        "REVIEW_PROCESS_STILL_RUNNING",
    ),
    (
        "review",
        "RECOVERY_REQUIRED",
        "recovery_still_required",
        {},
        "REVIEW_INTEGRATION_OUTCOME_MISMATCH",
    ),
    ("integration", "PREPARING", "prepare_succeeded", {}, "INTEGRATION_PREPARE_GUARD_UNMET"),
    (
        "integration",
        "PREPARING",
        "prepare_succeeded",
        _g(manifest_persisted=True),
        "INTEGRATION_PREPARE_GUARD_UNMET",
    ),
    ("integration", "PREPARING", "conflict_before_write", {}, "INTEGRATION_CONFLICT_AFTER_WRITE"),
    ("integration", "PREPARED", "begin_apply", {}, "INTEGRATION_PREPARE_GUARD_UNMET"),
    (
        "integration",
        "PREPARED",
        "begin_apply",
        _g(manifest_persisted=True),
        "INTEGRATION_PREPARE_GUARD_UNMET",
    ),
    ("integration", "APPLYING", "apply_succeeded", {}, "INTEGRATION_APPLY_INCOMPLETE"),
    ("integration", "APPLYING", "apply_failed", {}, "INTEGRATION_FAILURE_NOT_RECORDED"),
    (
        "integration",
        "VERIFYING",
        "verification_succeeded",
        {},
        "INTEGRATION_VERIFICATION_INCOMPLETE",
    ),
    (
        "integration",
        "VERIFYING",
        "verification_succeeded",
        _g(all_entries_verified=True),
        "INTEGRATION_VERIFICATION_INCOMPLETE",
    ),
    ("integration", "VERIFYING", "verification_failed", {}, "INTEGRATION_FAILURE_NOT_RECORDED"),
    (
        "integration",
        "COMPENSATING",
        "compensation_succeeded",
        {},
        "INTEGRATION_PREIMAGE_NOT_VERIFIED",
    ),
    (
        "integration",
        "COMPENSATING",
        "compensation_failed",
        {},
        "INTEGRATION_RECOVERY_EVIDENCE_REQUIRED",
    ),
    ("integration", "PREPARED", "recover", {}, "INTEGRATION_RECOVERY_EVIDENCE_REQUIRED"),
    (
        "integration",
        "PREPARED",
        "recover",
        _g(recovery_evidence_recorded=True),
        "INTEGRATION_RECOVERY_CLASSIFICATION_REQUIRED",
    ),
    (
        "integration",
        "PREPARED",
        "recover",
        _g(recovery_evidence_recorded=True, recovery_classification="ALL_PREIMAGE"),
        "INTEGRATION_PREIMAGE_NOT_VERIFIED",
    ),
    (
        "integration",
        "ACCEPT_RECOVERY_REQUIRED",
        "resolve_recovery_rolled_back",
        {},
        "INTEGRATION_RECOVERY_CLASSIFICATION_MISMATCH",
    ),
    (
        "integration",
        "ACCEPT_RECOVERY_REQUIRED",
        "resolve_recovery_rolled_back",
        _g(recovery_classification="ALL_PREIMAGE"),
        "INTEGRATION_PREIMAGE_NOT_VERIFIED",
    ),
    (
        "integration",
        "ACCEPT_RECOVERY_REQUIRED",
        "confirm_recovered_acceptance",
        {},
        "INTEGRATION_RECOVERY_CLASSIFICATION_MISMATCH",
    ),
    (
        "integration",
        "ACCEPT_RECOVERY_REQUIRED",
        "confirm_recovered_acceptance",
        _g(recovery_classification="ALL_POSTIMAGE"),
        "INTEGRATION_VERIFICATION_INCOMPLETE",
    ),
    (
        "integration",
        "ACCEPT_RECOVERY_REQUIRED",
        "confirm_recovered_acceptance",
        _g(recovery_classification="ALL_POSTIMAGE", all_entries_verified=True),
        "INTEGRATION_VERIFICATION_INCOMPLETE",
    ),
    (
        "integration",
        "ACCEPT_RECOVERY_REQUIRED",
        "confirm_recovered_acceptance",
        _g(
            recovery_classification="ALL_POSTIMAGE",
            all_entries_verified=True,
            required_validations_passed=True,
        ),
        "INTEGRATION_TRUSTED_CONFIRMATION_REQUIRED",
    ),
)


@pytest.mark.parametrize(("machine", "state", "event", "guard_values", "reason"), GUARD_FAILURES)
def test_guard_first_failure_order(
    contract: Contract,
    machine: str,
    state: str,
    event: str,
    guard_values: dict[str, Any],
    reason: str,
) -> None:
    assert_transition_case(
        contract.transitions[machine],
        contract.state_types[machine][state],
        contract.event_types[machine](event),
        _convert_guard(contract, machine, guard_values),
        reason_code=reason,
    )


@pytest.mark.parametrize("machine", ("run", "task", "review", "integration"))
def test_strict_state_event_and_guard_type_rejection(contract: Contract, machine: str) -> None:
    state_type, event_type, guard_type = (
        contract.state_types[machine],
        contract.event_types[machine],
        contract.guard_types[machine],
    )
    event = next(iter(event_type))
    valid_state = next(iter(state_type))
    invalid = f"{machine.upper()}_TRANSITION_INVALID"
    foreign_event = StrEnum("ForeignEvent", {"SAME": event.value})
    foreign_state = StrEnum("ForeignState", {"SAME": valid_state.value})
    bad_events = (
        event.value.upper(),
        f" {event.value}",
        f"{event.value} ",
        event.value.replace("_", "-"),
        None,
        0,
        True,
        object(),
        foreign_event.SAME,
    )
    for bad_event in (candidate for candidate in bad_events if candidate != event.value):
        assert_transition_case(
            contract.transitions[machine], valid_state, bad_event, guard_type(), reason_code=invalid
        )
    for bad_state in (valid_state.value, None, 0, True, object(), foreign_state.SAME):
        assert_transition_case(
            contract.transitions[machine], bad_state, event, guard_type(), reason_code=invalid
        )
    for bad_guards in ({}, object(), type("GuardSubclass", (guard_type,), {})()):
        assert_transition_case(
            contract.transitions[machine], valid_state, event, bad_guards, reason_code=invalid
        )


@pytest.mark.parametrize("machine", ("run", "task", "review", "integration"))
def test_guard_constructor_and_capability_mirror_drift_fail_closed(
    contract: Contract, machine: str
) -> None:
    guard_type = contract.guard_types[machine]
    annotations = inspect.get_annotations(guard_type)
    invalid = f"{machine.upper()}_TRANSITION_INVALID"
    foreign = StrEnum("ForeignBool", {"FALSE": "false"})
    for field, annotation in annotations.items():
        if annotation is bool:
            for bad in (0, 1, "true", "false", None, object(), foreign.FALSE):
                with pytest.raises(contract.transition_error, match=f"^{invalid}$"):
                    guard_type(**{field: bad})
            drifted = guard_type()
            object.__setattr__(drifted, field, "false")
            assert_transition_case(
                contract.transitions[machine],
                next(iter(contract.state_types[machine])),
                next(iter(contract.event_types[machine])),
                drifted,
                reason_code=invalid,
            )
        elif field == "review_state":
            for bad in ("READY", contract.state_types["run"].RUNNING, object()):
                with pytest.raises(contract.transition_error, match=f"^{invalid}$"):
                    guard_type(**{field: bad})
        elif field in {"integration_outcome", "prior_review_state", "recovery_classification"}:
            for bad in ("wrong", foreign.FALSE, object()):
                with pytest.raises(contract.transition_error, match=f"^{invalid}$"):
                    guard_type(**{field: bad})


@pytest.mark.parametrize("machine", ("run", "task", "review", "integration"))
def test_capability_mirror_extra_missing_and_wrong_guard_fields_fail_closed(
    contract: Contract, machine: str
) -> None:
    guard_type = contract.guard_types[machine]
    invalid = f"{machine.upper()}_TRANSITION_INVALID"
    state = next(iter(contract.state_types[machine]))
    event = next(iter(contract.event_types[machine]))
    field = next(iter(inspect.get_annotations(guard_type)))

    extra = guard_type()
    object.__setattr__(extra, "unexpected", True)
    assert_transition_case(contract.transitions[machine], state, event, extra, reason_code=invalid)
    assert vars(extra)["unexpected"] is True

    missing = guard_type()
    object.__delattr__(missing, field)
    assert_transition_case(contract.transitions[machine], state, event, missing, reason_code=invalid)
    assert field not in vars(missing)

    wrong_value = guard_type()
    object.__setattr__(wrong_value, field, "wrong")
    assert_transition_case(contract.transitions[machine], state, event, wrong_value, reason_code=invalid)
    assert vars(wrong_value)[field] == "wrong"

"""budget boundaries and no-progress breaker tests."""

from __future__ import annotations

import importlib

import pytest


def test_owned_budget_boundary_oracle() -> None:
    usage = {"decisions": 29, "runtime_ms": 3_599_999, "files": 19, "changed_lines": 1499}
    limits = {"decisions": 30, "runtime_ms": 3_600_000, "files": 20, "changed_lines": 1500}
    assert all(usage[key] + 1 >= limits[key] for key in usage)
    mutated = dict(usage)
    mutated["files"] = 18
    assert not all(mutated[key] + 1 >= limits[key] for key in mutated)


def load_runtime_control_contract():
    try:
        return importlib.import_module("yagcode.core.budget")
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.startswith("yagcode.core"):
            pytest.fail(f"RUNTIME_CONTROL_CONTRACT_MISSING: {error.name}")
        raise


@pytest.mark.parametrize(
    ("metric", "limit"),
    [("decisions", 30), ("runtime_ms", 3_600_000), ("files", 20), ("changed_lines", 1500)],
)
def test_each_resource_limit_pauses_at_boundary(metric: str, limit: int) -> None:
    budget = load_runtime_control_contract()
    tracker = budget.RuntimeBudget(budget.BudgetLimits())
    tracker.set_usage(metric, limit - 1)
    decision = tracker.consume(metric, 1)
    assert decision.state == "PAUSED_BUDGET"
    assert decision.reason_code == f"{metric.upper()}_LIMIT_REACHED"


def test_same_stable_error_pauses_on_third_occurrence() -> None:
    budget = load_runtime_control_contract()
    tracker = budget.RuntimeBudget(budget.BudgetLimits())
    assert tracker.record_stable_error("TEST_ASSERTION_FAILED").state == "RUNNING"
    assert tracker.record_stable_error("TEST_ASSERTION_FAILED").state == "RUNNING"
    assert tracker.record_stable_error("TEST_ASSERTION_FAILED").state == "PAUSED_FAILURE"
    assert tracker.record_stable_error("DIFFERENT").state == "RUNNING"

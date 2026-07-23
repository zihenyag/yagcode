"""Deterministic runtime budget and no-progress breaker."""

from __future__ import annotations

from dataclasses import dataclass


SAME_ERROR_PAUSE_COUNT = 3


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    decisions: int = 30
    runtime_ms: int = 3_600_000
    files: int = 20
    changed_lines: int = 1500


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    state: str
    reason_code: str
    metric: str | None = None
    usage: int | None = None
    limit: int | None = None


class RuntimeBudget:
    def __init__(self, limits: BudgetLimits) -> None:
        self._limits = limits
        self._usage = {
            "decisions": 0,
            "runtime_ms": 0,
            "files": 0,
            "changed_lines": 0,
        }
        self._last_error: str | None = None
        self._stable_error_count = 0

    def set_usage(self, metric: str, value: int) -> None:
        if metric not in self._usage or type(value) is not int or value < 0:
            raise ValueError("BUDGET_USAGE_INVALID")
        self._usage[metric] = value

    def consume(self, metric: str, amount: int) -> BudgetDecision:
        if metric not in self._usage or type(amount) is not int or amount < 0:
            raise ValueError("BUDGET_CONSUME_INVALID")
        usage = self._usage[metric] + amount
        self._usage[metric] = usage
        limit = _limit_for(self._limits, metric)
        if usage >= limit:
            return BudgetDecision(
                "PAUSED_BUDGET",
                f"{metric.upper()}_LIMIT_REACHED",
                metric,
                usage,
                limit,
            )
        return BudgetDecision("RUNNING", "BUDGET_AVAILABLE", metric, usage, limit)

    def record_stable_error(self, category: str) -> BudgetDecision:
        if type(category) is not str or not category:
            raise ValueError("BUDGET_ERROR_CATEGORY_INVALID")
        if category == self._last_error:
            self._stable_error_count += 1
        else:
            self._last_error = category
            self._stable_error_count = 1
        if self._stable_error_count >= SAME_ERROR_PAUSE_COUNT:
            return BudgetDecision("PAUSED_FAILURE", "SAME_ERROR_PAUSE_COUNT_REACHED")
        return BudgetDecision("RUNNING", "NO_PROGRESS_BREAKER_AVAILABLE")


def _limit_for(limits: BudgetLimits, metric: str) -> int:
    value = getattr(limits, metric, None)
    if type(value) is not int or value <= 0:
        raise ValueError("BUDGET_LIMIT_INVALID")
    return value


__all__ = ["BudgetDecision", "BudgetLimits", "RuntimeBudget", "SAME_ERROR_PAUSE_COUNT"]

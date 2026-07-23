"""Deterministic retry limits for Providers and governed tools."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


PROVIDER_MAX_TOTAL_ATTEMPTS = 5
READ_TOOL_MAX_TOTAL_ATTEMPTS = 3
SIDE_EFFECT_MAX_TOTAL_ATTEMPTS = 1
_PROVIDER_RETRYABLE = frozenset({"disconnect", "429", "retryable_5xx", "timeout"})
_TOOL_RETRYABLE = frozenset({"timeout", "disconnect"})


@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    success: bool
    category: str
    retry_after_ms: int | None = None


@dataclass(frozen=True, slots=True)
class RetryResult:
    success: bool
    category: str
    attempts: int
    model_switched: bool = False


class RecordingSleeper:
    def __init__(self) -> None:
        self.delays_ms: list[int] = []
        self.real_sleep_count = 0

    def sleep(self, delay_ms: int) -> None:
        self.delays_ms.append(delay_ms)


class RetryController:
    def __init__(self, *, sleeper: RecordingSleeper | None = None) -> None:
        self._sleeper = RecordingSleeper() if sleeper is None else sleeper

    def provider(self, operation: Callable[[], AttemptOutcome]) -> RetryResult:
        return self._run(
            operation,
            max_attempts=PROVIDER_MAX_TOTAL_ATTEMPTS,
            retryable_categories=_PROVIDER_RETRYABLE,
        )

    def tool(self, operation: Callable[[], AttemptOutcome], *, read_only: bool) -> RetryResult:
        return self._run(
            operation,
            max_attempts=READ_TOOL_MAX_TOTAL_ATTEMPTS
            if read_only
            else SIDE_EFFECT_MAX_TOTAL_ATTEMPTS,
            retryable_categories=_TOOL_RETRYABLE,
        )

    def _run(
        self,
        operation: Callable[[], AttemptOutcome],
        *,
        max_attempts: int,
        retryable_categories: frozenset[str],
    ) -> RetryResult:
        attempts = 0
        last = AttemptOutcome(False, "NOT_CALLED")
        while attempts < max_attempts:
            attempts += 1
            last = operation()
            if last.success:
                return RetryResult(True, last.category, attempts)
            if last.category not in retryable_categories or attempts == max_attempts:
                return RetryResult(False, last.category, attempts)
            self._sleeper.sleep(last.retry_after_ms if last.retry_after_ms is not None else 0)
        return RetryResult(False, last.category, attempts)


__all__ = [
    "AttemptOutcome",
    "PROVIDER_MAX_TOTAL_ATTEMPTS",
    "READ_TOOL_MAX_TOTAL_ATTEMPTS",
    "RecordingSleeper",
    "RetryController",
    "RetryResult",
    "SIDE_EFFECT_MAX_TOTAL_ATTEMPTS",
]

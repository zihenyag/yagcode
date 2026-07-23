"""retry classification tests without real sleeping."""

from __future__ import annotations

import importlib

import pytest


def test_owned_retry_attempt_oracle() -> None:
    retryable_categories = {"disconnect", "429", "retryable_5xx", "timeout"}
    assert all(category in retryable_categories for category in ("disconnect", "429", "timeout"))
    assert "auth" not in retryable_categories


def load_runtime_control_contract():
    try:
        return importlib.import_module("yagcode.core.retry")
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.startswith("yagcode.core"):
            pytest.fail(f"RUNTIME_CONTROL_CONTRACT_MISSING: {error.name}")
        raise


@pytest.mark.parametrize("category", ["disconnect", "429", "retryable_5xx", "timeout"])
def test_provider_total_attempts_are_exactly_five(category: str) -> None:
    retry = load_runtime_control_contract()
    operation = _AlwaysFail(retry, category)
    sleeper = retry.RecordingSleeper()
    result = retry.RetryController(sleeper=sleeper).provider(operation.call)
    assert operation.calls == 5
    assert result.attempts == 5
    assert result.category == category
    assert sleeper.real_sleep_count == 0


def test_non_retryable_provider_error_is_once_and_does_not_switch_model() -> None:
    retry = load_runtime_control_contract()
    operation = _AlwaysFail(retry, "auth")
    result = retry.RetryController(sleeper=retry.RecordingSleeper()).provider(operation.call)
    assert operation.calls == 1
    assert result.category == "auth"
    assert result.model_switched is False


def test_tool_retry_limits_follow_side_effect_class() -> None:
    retry = load_runtime_control_contract()
    read_operation = _AlwaysFail(retry, "timeout")
    side_effect_operation = _AlwaysFail(retry, "timeout")
    controller = retry.RetryController(sleeper=retry.RecordingSleeper())
    assert controller.tool(read_operation.call, read_only=True).attempts == 3
    assert controller.tool(side_effect_operation.call, read_only=False).attempts == 1


class _AlwaysFail:
    def __init__(self, retry, category: str) -> None:
        self._retry = retry
        self.category = category
        self.calls = 0

    def call(self):
        self.calls += 1
        return self._retry.AttemptOutcome(False, self.category)

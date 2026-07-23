"""objective feedback normalization tests."""

from __future__ import annotations

import importlib

import pytest

from yagcode.domain.results import ValidationResult


def test_owned_feedback_fixture_oracle() -> None:
    mapping = {"FAIL": "TEST_ASSERTION_FAILED", "PASS": "VALIDATION_PASSED"}
    assert mapping["FAIL"] == "TEST_ASSERTION_FAILED"
    mutated = dict(mapping)
    mutated["FAIL"] = "VALIDATION_PASSED"
    assert mutated["FAIL"] != mapping["FAIL"]


def load_feedback_contract():
    try:
        return importlib.import_module("yagcode.core.feedback")
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.startswith("yagcode.core"):
            pytest.fail(f"FEEDBACK_CONTRACT_MISSING: {error.name}")
        raise


def test_validation_result_normalizes_to_stable_feedback() -> None:
    feedback = load_feedback_contract()
    result = _validation("FAIL", "TEST_ASSERTION_FAILED")
    normalized = feedback.FeedbackNormalizer().from_validation(result)
    assert normalized.code == "TEST_ASSERTION_FAILED"
    assert normalized.status == "FAIL"
    assert normalized.source_action_id == "action-1"
    assert normalized.evidence_refs == ("artifact:test.log",)


def _validation(status: str, reason_code: str) -> ValidationResult:
    return ValidationResult(
        run_id="run-a",
        validator_id="unit",
        required=True,
        status=status,
        category="TEST",
        reason_code=reason_code,
        command_template_id="pytest-unit",
        summary="unit tests failed",
        evidence_refs=["artifact:test.log"],
        source_action_id="action-1",
        retryable=False,
    )

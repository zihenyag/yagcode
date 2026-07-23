"""review projection is controlled only by objective validation evidence."""

from __future__ import annotations

import importlib

import pytest

from yagcode.domain.errors import TransitionError
from yagcode.domain.results import ValidationResult
from yagcode.domain.states import ReviewState


def test_owned_validation_gate_oracle() -> None:
    statuses = ("PASS", "FAIL", "UNKNOWN", "MISSING")
    assert all(status == "PASS" for status in statuses[:1])
    assert not all(status == "PASS" for status in statuses)


def load_feedback_contract():
    try:
        return (
            importlib.import_module("yagcode.core.validation_gate"),
            importlib.import_module("yagcode.tools.validator_config"),
        )
    except ModuleNotFoundError as error:
        if error.name is not None and (
            error.name.startswith("yagcode.core") or error.name.startswith("yagcode.tools")
        ):
            pytest.fail(f"FEEDBACK_CONTRACT_MISSING: {error.name}")
        raise


@pytest.mark.parametrize("bad_status", ["FAIL", "UNKNOWN", "MISSING"])
def test_any_required_non_pass_is_incomplete(bad_status: str) -> None:
    gate, config = load_feedback_contract()
    state = gate.project_review(
        ReviewState.NOT_READY,
        _definitions(config),
        (_validation("unit", True, bad_status), _validation("lint", True, "PASS")),
    )
    assert state is ReviewState.INCOMPLETE


def test_absent_required_evidence_is_not_vacuously_ready() -> None:
    gate, config = load_feedback_contract()
    with pytest.raises(TransitionError, match="REVIEW_VALIDATIONS_NOT_EVALUATED"):
        gate.project_review(ReviewState.NOT_READY, _definitions(config), ())


def test_all_required_pass_projects_ready() -> None:
    gate, config = load_feedback_contract()
    state = gate.project_review(
        ReviewState.NOT_READY,
        _definitions(config),
        (_validation("unit", True, "PASS"), _validation("lint", True, "PASS")),
    )
    assert state is ReviewState.READY


def test_duplicate_or_unknown_validation_ids_fail_closed() -> None:
    gate, config = load_feedback_contract()
    definitions = _definitions(config)
    with pytest.raises(TransitionError, match="REVIEW_VALIDATIONS_NOT_EVALUATED"):
        gate.project_review(
            ReviewState.NOT_READY,
            definitions,
            (_validation("unit", True, "PASS"), _validation("unit", True, "PASS")),
        )
    with pytest.raises(TransitionError, match="REVIEW_VALIDATIONS_NOT_EVALUATED"):
        gate.project_review(
            ReviewState.NOT_READY,
            definitions,
            (_validation("unit", True, "PASS"), _validation("unknown", True, "PASS")),
        )


def _definitions(config):
    return (
        config.ValidatorDefinition("unit", "pytest-unit", ".", 60_000, True, "exit_zero"),
        config.ValidatorDefinition("lint", "ruff", ".", 60_000, True, "exit_zero"),
    )


def _validation(validator_id: str, required: bool, status: str) -> ValidationResult:
    return ValidationResult(
        run_id="run-a",
        validator_id=validator_id,
        required=required,
        status=status,
        category="TEST",
        reason_code="VALIDATION_" + status,
        command_template_id=validator_id,
        summary="validation",
        evidence_refs=["artifact"],
        retryable=False,
    )

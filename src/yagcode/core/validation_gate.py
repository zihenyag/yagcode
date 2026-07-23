"""Review projection from complete objective validation evidence."""

from __future__ import annotations

from yagcode.domain.errors import TransitionError
from yagcode.domain.results import ValidationResult
from yagcode.domain.states import ReviewState
from yagcode.domain.transitions import ReviewGuards, transition_review
from yagcode.tools.validator_config import ValidatorDefinition


def project_review(
    state: ReviewState,
    definitions: tuple[ValidatorDefinition, ...],
    validations: tuple[ValidationResult, ...],
) -> ReviewState:
    _validate_inputs(definitions, validations)
    required_ids = frozenset(item.validator_id for item in definitions if item.required)
    if not required_ids:
        raise TransitionError("REVIEW_VALIDATIONS_NOT_EVALUATED")
    result_ids = frozenset(item.validator_id for item in validations)
    if not required_ids <= result_ids:
        raise TransitionError("REVIEW_VALIDATIONS_NOT_EVALUATED")

    required_results = tuple(item for item in validations if item.validator_id in required_ids)
    required_passed = all(_status_value(item.status) == "PASS" for item in required_results)
    target = ReviewState.READY if required_passed else ReviewState.INCOMPLETE
    if state is target:
        return state
    event = "candidate_ready" if required_passed else "candidate_incomplete"
    return transition_review(
        state,
        event,
        ReviewGuards(
            validations_evaluated=True,
            required_validations_passed=required_passed,
        ),
    )


def _validate_inputs(
    definitions: tuple[ValidatorDefinition, ...],
    validations: tuple[ValidationResult, ...],
) -> None:
    if type(definitions) is not tuple or type(validations) is not tuple:
        raise TransitionError("REVIEW_VALIDATIONS_NOT_EVALUATED")
    definition_ids = tuple(item.validator_id for item in definitions)
    if len(definition_ids) != len(set(definition_ids)):
        raise TransitionError("REVIEW_VALIDATIONS_NOT_EVALUATED")
    definition_by_id = {item.validator_id: item for item in definitions}
    result_ids = tuple(item.validator_id for item in validations)
    if len(result_ids) != len(set(result_ids)):
        raise TransitionError("REVIEW_VALIDATIONS_NOT_EVALUATED")
    for result in validations:
        definition = definition_by_id.get(result.validator_id)
        if definition is None or result.required is not definition.required:
            raise TransitionError("REVIEW_VALIDATIONS_NOT_EVALUATED")


def _status_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return raw if type(raw) is str else "UNKNOWN"


__all__ = ["project_review"]

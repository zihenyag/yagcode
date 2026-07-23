"""Immutable validator definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SuccessPredicate = Literal["exit_zero", "expected_failure", "structured_json"]


@dataclass(frozen=True, slots=True)
class ValidatorDefinition:
    validator_id: str
    command_template_id: str
    canonical_cwd: str
    timeout_ms: int
    required: bool
    success_predicate: SuccessPredicate

    def __post_init__(self) -> None:
        for value in (self.validator_id, self.command_template_id, self.canonical_cwd):
            if type(value) is not str or not value or "\x00" in value:
                raise ValueError("VALIDATOR_DEFINITION_TEXT_INVALID")
        if type(self.timeout_ms) is not int or self.timeout_ms <= 0:
            raise ValueError("VALIDATOR_TIMEOUT_INVALID")
        if type(self.required) is not bool:
            raise ValueError("VALIDATOR_REQUIRED_INVALID")
        if self.success_predicate not in {"exit_zero", "expected_failure", "structured_json"}:
            raise ValueError("VALIDATOR_SUCCESS_PREDICATE_INVALID")


__all__ = ["SuccessPredicate", "ValidatorDefinition"]

"""Normalize objective tool and validation results into loop feedback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from yagcode.domain.results import ToolResult, ValidationResult

from .ports import FeedbackRecord


FeedbackStatus = Literal["PASS", "FAIL", "UNKNOWN"]


@dataclass(frozen=True, slots=True)
class Feedback:
    code: str
    status: FeedbackStatus
    summary: str
    evidence_refs: tuple[str, ...]
    source_action_id: str
    reason_code: str


class FeedbackNormalizer:
    def from_validation(self, result: ValidationResult) -> Feedback:
        status = _status_value(result.status)
        return Feedback(
            code=result.reason_code,
            status="PASS" if status == "PASS" else "FAIL" if status in {"FAIL", "MISSING"} else "UNKNOWN",
            summary=result.summary,
            evidence_refs=tuple(result.evidence_refs),
            source_action_id=result.source_action_id or result.validator_id,
            reason_code=result.reason_code,
        )

    def normalize(self, action: object, result: ToolResult) -> FeedbackRecord:
        return FeedbackRecord(result.reason_code)


def _status_value(value: object) -> str:
    raw = getattr(value, "value", value)
    if type(raw) is not str:
        return "UNKNOWN"
    return raw


__all__ = ["Feedback", "FeedbackNormalizer", "FeedbackStatus"]

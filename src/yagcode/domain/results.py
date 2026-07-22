"""Public, strict result contracts shared by tools and validators."""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationInfo,
    field_validator,
)


class ToolStatus(str, Enum):
    """Terminal status of a tool action."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"


class SideEffectState(str, Enum):
    """Known state of a tool action's side effects."""

    NONE = "NONE"
    APPLIED = "APPLIED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class ValidationStatus(str, Enum):
    """Outcome status of a deterministic validation."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    MISSING = "MISSING"


ShortText = Annotated[StrictStr, Field(min_length=1, max_length=128)]
SummaryText = Annotated[StrictStr, Field(min_length=1, max_length=4000)]
ArtifactRef = Annotated[StrictStr, Field(min_length=1, max_length=1024)]
ExitCode = Annotated[StrictInt, Field(ge=-2_147_483_648, le=2_147_483_647)]


class _ResultContract(BaseModel):
    """Shared safeguards that are not expressed by Pydantic field metadata."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before", check_fields=False)
    @classmethod
    def reject_nul_and_non_list_references(
        cls, value: object, info: ValidationInfo
    ) -> object:
        if info.field_name in {"artifact_refs", "evidence_refs"}:
            if not isinstance(value, list):
                raise ValueError("reference fields must be lists")
            if any(isinstance(item, str) and "\x00" in item for item in value):
                raise ValueError("strings must not contain NUL")
        elif isinstance(value, str) and "\x00" in value:
            raise ValueError("strings must not contain NUL")
        return value


class ToolResult(_ResultContract):
    """Observable result of executing one tool action."""

    action_id: ShortText
    status: ToolStatus
    category: ShortText
    reason_code: ShortText
    exit_code: ExitCode | None = None
    artifact_refs: list[ArtifactRef] = Field(default_factory=list, min_length=0, max_length=100)
    side_effect_state: SideEffectState
    retryable: StrictBool


class ValidationResult(_ResultContract):
    """Observable result of one deterministic validation."""

    run_id: ShortText
    validator_id: ShortText
    required: StrictBool
    status: ValidationStatus
    category: ShortText
    reason_code: ShortText
    command_template_id: ShortText
    exit_code: ExitCode | None = None
    summary: SummaryText
    evidence_refs: list[ArtifactRef] = Field(default_factory=list, min_length=0, max_length=100)
    source_action_id: ShortText | None = None
    retryable: StrictBool

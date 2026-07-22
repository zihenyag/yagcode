"""Strict, immutable action contracts accepted by the deterministic parser.

These models describe already-decoded JSON candidates only.  They neither
resolve targets nor perform policy, persistence, tool, Git, or I/O work.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_serializer,
    field_validator,
    model_validator,
)


type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


ActionId = Annotated[StrictStr, Field(min_length=1, max_length=128)]
RunId = Annotated[StrictStr, Field(min_length=1, max_length=128)]
RootId = Annotated[StrictStr, Field(min_length=1, max_length=128)]
RequiredPath = Annotated[StrictStr, Field(min_length=1, max_length=1024)]
OptionalPath = Annotated[StrictStr, Field(min_length=0, max_length=1024)]
ReasonSummary = Annotated[StrictStr, Field(min_length=1, max_length=2000)]
ShortText = Annotated[StrictStr, Field(min_length=1, max_length=128)]
ArgumentKey = Annotated[StrictStr, Field(min_length=1, max_length=64)]
ArgumentValue = Annotated[StrictStr, Field(min_length=0, max_length=1024)]
HunkText = Annotated[StrictStr, Field(min_length=0, max_length=65_536)]


def _reject_nul(value: object) -> None:
    """Reject NUL recursively without retaining a candidate value in an error."""

    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("NUL is not permitted")
        return
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_nul(key)
            _reject_nul(nested)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            _reject_nul(nested)


class _FrozenActionModel(BaseModel):
    """Shared strictness, closed-object semantics, and direct-model NUL guard."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="after")
    def reject_nested_nul_strings(self) -> _FrozenActionModel:
        for value in self.__dict__.values():
            _reject_nul(value)
        return self


class ActionBase(_FrozenActionModel):
    """Common required fields carried by every action branch."""

    action_id: ActionId
    run_id: RunId
    generation: Annotated[StrictInt, Field(ge=0)]
    reason_summary: ReasonSummary

    @field_validator("action_id", "run_id", "reason_summary", mode="before")
    @classmethod
    def reject_nul_common_strings(cls, value: object) -> object:
        _reject_nul(value)
        return value


class ListDirectoryPayload(_FrozenActionModel):
    root_id: RootId
    relative_path: OptionalPath
    max_depth: Annotated[StrictInt, Field(ge=0, le=16)]
    max_entries: Annotated[StrictInt, Field(ge=1, le=1000)]


class ListDirectoryAction(ActionBase):
    kind: Literal["list_directory"]
    payload: ListDirectoryPayload


class ReadTextPayload(_FrozenActionModel):
    root_id: RootId
    relative_path: RequiredPath
    start_line: Annotated[StrictInt, Field(ge=1)]
    end_line: Annotated[StrictInt, Field(ge=1)]
    max_bytes: Annotated[StrictInt, Field(ge=1, le=1_048_576)]

    @model_validator(mode="after")
    def end_line_must_not_precede_start_line(self) -> ReadTextPayload:
        if self.end_line < self.start_line:
            raise ValueError("end line must not precede start line")
        return self


class ReadTextAction(ActionBase):
    kind: Literal["read_text"]
    payload: ReadTextPayload


class SearchLiteralPayload(_FrozenActionModel):
    root_id: RootId
    relative_path: OptionalPath
    query: Annotated[StrictStr, Field(min_length=1, max_length=512)]
    globs: Annotated[tuple[Annotated[StrictStr, Field(min_length=1, max_length=128)], ...], Field(
        min_length=0, max_length=20, strict=False
    )]
    max_results: Annotated[StrictInt, Field(ge=1, le=500)]


class SearchLiteralAction(ActionBase):
    kind: Literal["search_literal"]
    payload: SearchLiteralPayload


class PatchHunk(_FrozenActionModel):
    start_line: Annotated[StrictInt, Field(ge=1)]
    delete_line_count: Annotated[StrictInt, Field(ge=0, le=10_000)]
    expected_text: HunkText
    replacement_text: HunkText


class ApplyPatchPayload(_FrozenActionModel):
    root_id: RootId
    relative_path: RequiredPath
    base_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    hunks: Annotated[tuple[PatchHunk, ...], Field(min_length=1, max_length=50, strict=False)]


class ApplyPatchAction(ActionBase):
    kind: Literal["apply_patch"]
    payload: ApplyPatchPayload


class GitInspectPayload(_FrozenActionModel):
    operation: Literal["head", "status", "index", "worktree", "common_dir"]


class GitInspectAction(ActionBase):
    kind: Literal["git_inspect"]
    payload: GitInspectPayload


class RunCommandPayload(_FrozenActionModel):
    template_id: ShortText
    arguments: Annotated[Mapping[ArgumentKey, ArgumentValue], Field(max_length=32)]
    cwd_root_id: RootId
    cwd_relative_path: OptionalPath
    timeout_ms: Annotated[StrictInt, Field(ge=1000, le=600_000)]

    @field_validator("arguments")
    @classmethod
    def freeze_arguments(
        cls, value: Mapping[str, str]
    ) -> Mapping[str, str]:
        return MappingProxyType(dict(value))

    @field_serializer("arguments", when_used="json")
    def serialize_arguments(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


class RunCommandAction(ActionBase):
    kind: Literal["run_command"]
    payload: RunCommandPayload


class RunValidationPayload(_FrozenActionModel):
    validator_id: ShortText
    target_paths: Annotated[tuple[RequiredPath, ...], Field(min_length=1, max_length=100, strict=False)]


class RunValidationAction(ActionBase):
    kind: Literal["run_validation"]
    payload: RunValidationPayload


class RequestReviewPayload(_FrozenActionModel):
    summary: Annotated[StrictStr, Field(min_length=1, max_length=4000)]
    uncovered: Annotated[tuple[RequiredPath, ...], Field(min_length=0, max_length=100, strict=False)]


class RequestReviewAction(ActionBase):
    kind: Literal["request_review"]
    payload: RequestReviewPayload


type Action = Annotated[
    ListDirectoryAction
    | ReadTextAction
    | SearchLiteralAction
    | ApplyPatchAction
    | GitInspectAction
    | RunCommandAction
    | RunValidationAction
    | RequestReviewAction,
    Field(discriminator="kind"),
]


__all__ = [
    "Action",
    "ActionBase",
    "ApplyPatchAction",
    "ApplyPatchPayload",
    "GitInspectAction",
    "GitInspectPayload",
    "JsonValue",
    "ListDirectoryAction",
    "ListDirectoryPayload",
    "PatchHunk",
    "ReadTextAction",
    "ReadTextPayload",
    "RequestReviewAction",
    "RequestReviewPayload",
    "RunCommandAction",
    "RunCommandPayload",
    "RunValidationAction",
    "RunValidationPayload",
    "SearchLiteralAction",
    "SearchLiteralPayload",
]

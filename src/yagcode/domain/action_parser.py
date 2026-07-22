"""Pure conversion from an already-decoded JSON candidate to one action."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, cast

from pydantic import TypeAdapter, ValidationError

from .actions import Action, JsonValue


type ActionIssueCode = Literal[
    "ACTION_SHAPE_INVALID",
    "ACTION_FIELD_REQUIRED",
    "ACTION_FIELD_UNKNOWN",
    "ACTION_TYPE_INVALID",
    "ACTION_BOUND_INVALID",
    "ACTION_PATTERN_INVALID",
    "ACTION_ENUM_INVALID",
    "ACTION_RELATION_INVALID",
]


@dataclass(frozen=True)
class ActionParseIssue:
    """A stable, value-free description of one invalid contract location."""

    path: str
    code: ActionIssueCode


@dataclass(frozen=True)
class ActionParseSuccess:
    """The one strictly validated action selected by the candidate's kind."""

    action: Action


@dataclass(frozen=True)
class ActionParseFailure:
    """A bounded, deterministic failure that intentionally retains no input."""

    reason_code: Literal["ACTION_CANDIDATE_INVALID"]
    issues: tuple[ActionParseIssue, ...]
    truncated: bool


_ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)
_TOP_LEVEL_FIELDS = frozenset(
    {"action_id", "run_id", "generation", "kind", "reason_summary", "payload"}
)
_PAYLOAD_FIELDS: dict[str, frozenset[str]] = {
    "list_directory": frozenset({"root_id", "relative_path", "max_depth", "max_entries"}),
    "read_text": frozenset({"root_id", "relative_path", "start_line", "end_line", "max_bytes"}),
    "search_literal": frozenset({"root_id", "relative_path", "query", "globs", "max_results"}),
    "apply_patch": frozenset({"root_id", "relative_path", "base_sha256", "hunks"}),
    "git_inspect": frozenset({"operation"}),
    "run_command": frozenset(
        {"template_id", "arguments", "cwd_root_id", "cwd_relative_path", "timeout_ms"}
    ),
    "run_validation": frozenset({"validator_id", "target_paths"}),
    "request_review": frozenset({"summary", "uncovered"}),
}
_HUNK_FIELDS = frozenset({"start_line", "delete_line_count", "expected_text", "replacement_text"})
_ACTION_KINDS = frozenset(_PAYLOAD_FIELDS)
_MISSING_VALUE = object()


def _escape_pointer_segment(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def _join_pointer(path: str, segment: str) -> str:
    return f"{path}/{_escape_pointer_segment(segment)}"


def _candidate_kind(candidate: object) -> str | None:
    if type(candidate) is not dict:
        return None
    kind = candidate.get("kind")
    if type(kind) is str and kind in _ACTION_KINDS:
        return kind
    return None


def _trusted_child_segment(path: str, key: str, kind: str | None) -> str:
    """Return a declared key, or a literal star for every untrusted key."""

    if path == "":
        return key if key in _TOP_LEVEL_FIELDS else "*"
    if path == "/payload" and kind is not None:
        return key if key in _PAYLOAD_FIELDS[kind] else "*"
    if path.startswith("/payload/hunks/"):
        return key if key in _HUNK_FIELDS else "*"
    return "*"


def _json_domain_issues(candidate: object) -> tuple[ActionParseIssue, ...]:
    """Validate the recursive JSON domain before Pydantic sees a host object."""

    issues: list[ActionParseIssue] = []
    kind = _candidate_kind(candidate)

    def visit(value: object, path: str) -> None:
        value_type = type(value)
        if value is None or value_type is bool or value_type is int:
            return
        if value_type is float:
            if not math.isfinite(cast(float, value)):
                issues.append(ActionParseIssue(path, "ACTION_TYPE_INVALID"))
            return
        if value_type is str:
            if "\x00" in cast(str, value):
                issues.append(ActionParseIssue(path, "ACTION_PATTERN_INVALID"))
            return
        if value_type is list:
            for index, nested in enumerate(cast(list[object], value)):
                visit(nested, _join_pointer(path, str(index)))
            return
        if value_type is dict:
            for key, nested in cast(dict[object, object], value).items():
                if type(key) is not str:
                    issues.append(ActionParseIssue(_join_pointer(path, "*"), "ACTION_TYPE_INVALID"))
                    continue
                child_segment = _trusted_child_segment(path, key, kind)
                child_path = _join_pointer(path, child_segment)
                if "\x00" in key:
                    issues.append(ActionParseIssue(child_path, "ACTION_PATTERN_INVALID"))
                visit(nested, child_path)
            return
        issues.append(ActionParseIssue(path, "ACTION_TYPE_INVALID"))

    visit(candidate, "")
    return tuple(issues)


def _copy_json(candidate: JsonValue) -> JsonValue:
    """Defensively detach legal JSON input before model construction."""

    value_type = type(candidate)
    if value_type is list:
        return [_copy_json(item) for item in cast(list[JsonValue], candidate)]
    if value_type is dict:
        return {
            key: _copy_json(value)
            for key, value in cast(dict[str, JsonValue], candidate).items()
        }
    return candidate


def _pydantic_code(error_type: str, enum_value_is_string: bool | None = None) -> ActionIssueCode:
    """Map only Pydantic's structural type token, never its text or input."""

    if error_type == "missing":
        return "ACTION_FIELD_REQUIRED"
    if error_type == "extra_forbidden":
        return "ACTION_FIELD_UNKNOWN"
    if error_type == "string_pattern_mismatch":
        return "ACTION_PATTERN_INVALID"
    if error_type == "literal_error" and enum_value_is_string is False:
        return "ACTION_TYPE_INVALID"
    if error_type in {"literal_error", "union_tag_invalid", "union_tag_not_found"}:
        return "ACTION_ENUM_INVALID"
    if error_type in {
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "string_too_short",
        "string_too_long",
        "too_short",
        "too_long",
    }:
        return "ACTION_BOUND_INVALID"
    if error_type == "value_error":
        return "ACTION_RELATION_INVALID"
    return "ACTION_TYPE_INVALID"


def _location_path(location: object, kind: str | None, error_type: str) -> str:
    """Normalize a Pydantic location without exposing union labels or keys."""

    if error_type in {"union_tag_invalid", "union_tag_not_found"}:
        return "/kind"
    if not isinstance(location, tuple):
        return ""
    raw_segments = list(location)
    if raw_segments and raw_segments[0] in _ACTION_KINDS:
        raw_segments.pop(0)
    path = ""
    for segment in raw_segments:
        if type(segment) is int:
            path = _join_pointer(path, str(segment))
            continue
        if type(segment) is not str:
            return path
        trusted_segment = _trusted_child_segment(path, segment, kind)
        path = _join_pointer(path, trusted_segment)
    return path


def _value_at_location(candidate: dict[str, JsonValue], location: object) -> object:
    """Inspect only the runtime type at a structured error location."""

    if not isinstance(location, tuple):
        return _MISSING_VALUE
    segments = list(location)
    if segments and segments[0] in _ACTION_KINDS:
        segments.pop(0)
    current: object = candidate
    for segment in segments:
        if type(current) is dict and type(segment) is str:
            mapping = cast(dict[str, JsonValue], current)
            if segment not in mapping:
                return _MISSING_VALUE
            current = mapping[segment]
        elif type(current) is list and type(segment) is int:
            sequence = cast(list[JsonValue], current)
            if segment < 0 or segment >= len(sequence):
                return _MISSING_VALUE
            current = sequence[segment]
        else:
            return _MISSING_VALUE
    return current


def _issues_from_validation(
    error: ValidationError, candidate: dict[str, JsonValue]
) -> tuple[ActionParseIssue, ...]:
    """Extract only structured locations/types from Pydantic's validation tree."""

    kind = _candidate_kind(candidate)
    issues: list[ActionParseIssue] = []
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        error_type = item.get("type")
        if type(error_type) is not str:
            issues.append(ActionParseIssue("", "ACTION_SHAPE_INVALID"))
            continue
        location = item.get("loc")
        enum_value_is_string: bool | None = None
        if error_type == "literal_error":
            enum_value_is_string = type(_value_at_location(candidate, location)) is str
        issues.append(
            ActionParseIssue(
                _location_path(location, kind, error_type),
                _pydantic_code(error_type, enum_value_is_string),
            )
        )
    return tuple(issues)


def _normalize_issues(
    issues: list[ActionParseIssue] | tuple[ActionParseIssue, ...],
) -> tuple[tuple[ActionParseIssue, ...], bool]:
    """Sort, deduplicate, and cap public diagnostics at the fixed contract limit."""

    normalized = tuple(sorted(set(issues), key=lambda issue: (issue.path, issue.code)))
    return normalized[:32], len(normalized) > 32


def _failure(issues: list[ActionParseIssue] | tuple[ActionParseIssue, ...]) -> ActionParseFailure:
    normalized, truncated = _normalize_issues(issues)
    if not normalized:
        normalized = (ActionParseIssue("", "ACTION_SHAPE_INVALID"),)
    return ActionParseFailure(
        reason_code="ACTION_CANDIDATE_INVALID",
        issues=normalized,
        truncated=truncated,
    )


class ActionParser:
    """The sole public, deterministic, side-effect-free candidate parser."""

    def parse(self, candidate: JsonValue) -> ActionParseSuccess | ActionParseFailure:
        domain_issues = _json_domain_issues(candidate)
        if domain_issues:
            return _failure(domain_issues)
        if type(candidate) is not dict:
            return _failure((ActionParseIssue("", "ACTION_SHAPE_INVALID"),))
        json_candidate = candidate
        if "actions" in json_candidate:
            return _failure((ActionParseIssue("", "ACTION_SHAPE_INVALID"),))
        if "kind" not in json_candidate:
            return _failure((ActionParseIssue("/kind", "ACTION_FIELD_REQUIRED"),))
        kind = json_candidate.get("kind")
        if type(kind) is not str:
            return _failure((ActionParseIssue("/kind", "ACTION_TYPE_INVALID"),))
        if kind not in _ACTION_KINDS:
            return _failure((ActionParseIssue("/kind", "ACTION_ENUM_INVALID"),))
        payload = json_candidate.get("payload")
        if payload is not None and type(payload) is not dict:
            return _failure((ActionParseIssue("/payload", "ACTION_SHAPE_INVALID"),))
        try:
            action = _ACTION_ADAPTER.validate_python(_copy_json(json_candidate))
        except ValidationError as validation_error:
            return _failure(_issues_from_validation(validation_error, json_candidate))
        except Exception:
            return _failure((ActionParseIssue("", "ACTION_SHAPE_INVALID"),))
        return ActionParseSuccess(action=action)


__all__ = [
    "ActionParseFailure",
    "ActionParseIssue",
    "ActionParseSuccess",
    "ActionParser",
]

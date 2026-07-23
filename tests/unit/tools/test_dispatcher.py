"""dispatcher, metadata, file-read, and literal-search contracts."""

from __future__ import annotations

import hashlib
import importlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from yagcode.domain.actions import (
    ReadTextAction,
    ReadTextPayload,
    SearchLiteralAction,
    SearchLiteralPayload,
)
from yagcode.domain.results import SideEffectState, ToolResult, ToolStatus


def _read_action(action_id: str = "read-1", *, max_bytes: int = 128) -> ReadTextAction:
    return ReadTextAction(
        kind="read_text",
        action_id=action_id,
        run_id="run-1",
        generation=0,
        reason_summary="inspect file",
        payload=ReadTextPayload(
            root_id="shadow",
            relative_path="a.txt",
            start_line=1,
            end_line=20,
            max_bytes=max_bytes,
        ),
    )


def _search_action(query: str, *, max_results: int = 10) -> SearchLiteralAction:
    return SearchLiteralAction(
        kind="search_literal",
        action_id="search-1",
        run_id="run-1",
        generation=0,
        reason_summary="literal search",
        payload=SearchLiteralPayload(
            root_id="shadow",
            relative_path="",
            query=query,
            globs=("*.txt",),
            max_results=max_results,
        ),
    )


def test_owned_dispatcher_oracle_rejects_before_effects_and_orders_success() -> None:
    events: list[str] = []
    consumed = False

    def execute(token: str | None) -> bool:
        nonlocal consumed
        if token != "token" or consumed:
            return False
        consumed = True
        events.extend(("token", "intent", "backend", "result"))
        return True

    assert not execute(None)
    assert events == []
    assert execute("token")
    assert events == ["token", "intent", "backend", "result"]
    assert not execute("token")
    assert events == ["token", "intent", "backend", "result"]


def load_tools():
    try:
        return importlib.import_module("yagcode.tools")
    except ModuleNotFoundError as error:
        pytest.fail(f"TOOLS_CONTRACT_MISSING: {error.name}")


def load_files():
    try:
        return importlib.import_module("yagcode.tools.files")
    except ModuleNotFoundError as error:
        pytest.fail(f"TOOLS_CONTRACT_MISSING: {error.name}")


def load_search():
    try:
        return importlib.import_module("yagcode.tools.search")
    except ModuleNotFoundError as error:
        pytest.fail(f"TOOLS_CONTRACT_MISSING: {error.name}")


@dataclass
class Backend:
    events: list[str]
    calls: int = 0

    def execute(self, action: ReadTextAction) -> ToolResult:
        self.calls += 1
        self.events.append("backend")
        return ToolResult(
            action_id=action.action_id,
            status=ToolStatus.SUCCEEDED,
            category="READ",
            reason_code="READ_OK",
            side_effect_state=SideEffectState.NONE,
            retryable=True,
        )


class Journal:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def record_intent(self, action: ReadTextAction, *, side_effecting: bool) -> None:
        self.events.append(f"intent:{side_effecting}")

    def record_result(self, action: ReadTextAction, result: ToolResult) -> None:
        self.events.append("result")


def test_dispatcher_denials_have_no_backend_or_journal_and_success_consumes_first() -> None:
    tools = load_tools()
    events: list[str] = []
    token_store = tools.InMemoryExecutionTokenStore(events=events)
    backend = Backend(events)
    dispatcher = tools.ToolDispatcher(
        backends={"read_text": backend},
        journal=Journal(events),
        token_store=token_store,
    )
    action = _read_action()
    token = dispatcher.issue_token(action)

    assert dispatcher.execute(action, None).reason_code == "EXECUTION_TOKEN_REQUIRED"
    assert dispatcher.execute(_read_action("other"), token).reason_code == "EXECUTION_TOKEN_MISMATCH"
    assert backend.calls == 0
    assert events == []

    result = dispatcher.execute(action, token)
    assert result.status is ToolStatus.SUCCEEDED
    assert events == ["token_consumed", "intent:False", "backend", "result"]
    assert backend.calls == 1

    assert dispatcher.execute(action, token).reason_code == "EXECUTION_TOKEN_CONSUMED"
    assert events == ["token_consumed", "intent:False", "backend", "result"]
    assert backend.calls == 1


def test_dispatcher_unregistered_tool_is_denied_without_consuming_token() -> None:
    tools = load_tools()
    events: list[str] = []
    dispatcher = tools.ToolDispatcher(backends={}, token_store=tools.InMemoryExecutionTokenStore(events=events))
    action = _read_action()
    token = dispatcher.issue_token(action)

    assert dispatcher.execute(action, token).reason_code == "TOOL_UNREGISTERED"
    assert events == []
    assert dispatcher.execute(action, token).reason_code == "TOOL_UNREGISTERED"


def test_only_read_tools_are_retryable_and_registry_is_immutable() -> None:
    tools = load_tools()
    registry = tools.default_tool_registry()
    assert registry["read_text"].max_total_attempts == 3
    assert registry["search_literal"].max_total_attempts == 3
    assert registry["apply_patch"].max_total_attempts == 1
    assert registry["run_command"].max_total_attempts == 1
    with pytest.raises((AttributeError, TypeError)):
        registry["read_text"].max_total_attempts = 1
    with pytest.raises(TypeError):
        registry["read_text"] = registry["apply_patch"]


def test_read_text_action_returns_hash_truncation_and_rejects_escape(tmp_path: Path) -> None:
    files = load_files()
    payload = "alpha\nbeta\ngamma\n".encode()
    (tmp_path / "a.txt").write_bytes(payload)

    result = files.read_text_action(_read_action(max_bytes=9), roots={"shadow": tmp_path})
    assert result.status is ToolStatus.SUCCEEDED
    assert result.category == "READ_TRUNCATED"
    returned = b"alpha\nbet"
    assert result.artifact_refs == [
        f"sha256:{hashlib.sha256(returned).hexdigest()}",
        "bytes:9",
        "truncated:true",
    ]
    escaped = _read_action().model_copy(
        update={"payload": _read_action().payload.model_copy(update={"relative_path": "../a.txt"})}
    )
    assert files.read_text_action(escaped, roots={"shadow": tmp_path}).status is ToolStatus.DENIED


def test_search_literal_is_not_regex_and_obeys_result_bound(tmp_path: Path) -> None:
    search = load_search()
    (tmp_path / "a.txt").write_text("axb\na.b\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("a.b again\n", encoding="utf-8")

    result = search.search_action(_search_action("a.b", max_results=1), roots={"shadow": tmp_path})
    assert result.status is ToolStatus.SUCCEEDED
    assert result.artifact_refs == ["match:a.txt:2"]
    assert result.reason_code == "SEARCH_TRUNCATED"

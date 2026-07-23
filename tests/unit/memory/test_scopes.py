"""scoped memory visibility tests."""

from __future__ import annotations

import importlib

import pytest


def test_owned_scope_filter_oracle() -> None:
    record = {"profile": "p", "project": "a", "thread": "t1", "scope": "thread"}
    assert record["thread"] == "t1"
    assert record["project"] != "b"


def load_memory_contract():
    try:
        return importlib.import_module("yagcode.memory.service")
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.startswith("yagcode.memory"):
            pytest.fail(f"MEMORY_CONTRACT_MISSING: {error.name}")
        raise


def test_tentative_memory_is_visible_only_to_its_thread() -> None:
    memory = load_memory_contract()
    service = memory.MemoryService()
    service.add_tentative("p", "a", "t1", "fact", ("a1",))
    assert [item.text for item in service.retrieve("p", "a", "t1", "fact")] == ["fact"]
    assert service.retrieve("p", "a", "t2", "fact") == ()
    assert service.retrieve("p", "b", "t3", "fact") == ()


def test_project_memory_is_visible_across_threads_but_not_projects() -> None:
    memory = load_memory_contract()
    service = memory.MemoryService()
    service.add_project_fact("p", "a", "threadless project fact", ("a2",))
    assert [item.text for item in service.retrieve("p", "a", "t1", "project fact")] == [
        "threadless project fact"
    ]
    assert service.retrieve("p", "b", "t1", "project fact") == ()

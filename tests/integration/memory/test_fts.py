"""bounded retrieval tests."""

from __future__ import annotations

import importlib

import pytest


def test_owned_fts_limit_oracle() -> None:
    results = list(range(20))[:12]
    assert len(results) == 12
    assert 13 not in results


def load_memory_contract():
    try:
        return importlib.import_module("yagcode.memory.service")
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.startswith("yagcode.memory"):
            pytest.fail(f"MEMORY_CONTRACT_MISSING: {error.name}")
        raise


def test_retrieval_applies_scope_before_limit_and_text_match() -> None:
    memory = load_memory_contract()
    service = memory.MemoryService()
    for index in range(20):
        service.add_project_fact("p", "a", f"needle fact {index}", (f"s{index}",))
    service.add_project_fact("p", "b", "needle other project", ("other",))
    results = service.retrieve("p", "a", "t1", "needle")
    assert len(results) == 12
    assert all(item.project_id == "a" for item in results)
    assert all("needle" in item.text for item in results)

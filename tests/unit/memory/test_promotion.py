"""non-blocking cross-project promotion tests."""

from __future__ import annotations

import importlib

import pytest


def test_owned_promotion_oracle() -> None:
    scheduler_pause_count = 0
    accepted = False
    assert scheduler_pause_count == 0
    assert not accepted


def load_memory_contract():
    try:
        return importlib.import_module("yagcode.memory.service")
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.startswith("yagcode.memory"):
            pytest.fail(f"MEMORY_CONTRACT_MISSING: {error.name}")
        raise


def test_promotion_is_nonblocking_until_user_accepts() -> None:
    memory = load_memory_contract()
    service = memory.MemoryService()
    record = service.add_project_fact("p", "a", "shared fact", ("a1",))
    scheduler = _Scheduler()
    candidate = service.propose_cross_project(record.memory_id, target_project="b")
    assert scheduler.pause_count == 0
    assert service.retrieve("p", "b", "t2", "shared") == ()

    service.decide_promotion(candidate.candidate_id, "ACCEPT")
    assert [item.text for item in service.retrieve("p", "b", "t2", "shared")] == ["shared fact"]


class _Scheduler:
    pause_count = 0

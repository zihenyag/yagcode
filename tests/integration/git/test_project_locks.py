from __future__ import annotations

import importlib
from pathlib import Path


def test_owned_overlap_oracle(tmp_path: Path) -> None:
    assert (tmp_path / "a").resolve() != (tmp_path / "b").resolve()


def test_project_locks_reject_overlapping_write_roots(tmp_path: Path) -> None:
    locks = importlib.import_module("yagcode.git.locks")
    registry = locks.ProjectLockRegistry()
    first = registry.acquire((tmp_path / "workspace",), ())
    try:
        try:
            registry.acquire((tmp_path / "workspace" / "nested",), ())
        except locks.ProjectLockError as error:
            assert error.reason_code == "PROJECT_LOCK_OVERLAP"
        else:
            raise AssertionError("overlapping root was accepted")
    finally:
        first.release()


def test_project_locks_persist_across_registry_instances(tmp_path: Path) -> None:
    locks = importlib.import_module("yagcode.git.locks")
    lock_dir = tmp_path / "locks"
    first_registry = locks.ProjectLockRegistry(lock_dir)
    second_registry = locks.ProjectLockRegistry(lock_dir)
    first = first_registry.acquire((tmp_path / "workspace",), ())
    try:
        try:
            second_registry.acquire((tmp_path / "workspace" / "nested",), ())
        except locks.ProjectLockError as error:
            assert error.reason_code == "PROJECT_LOCK_OVERLAP"
        else:
            raise AssertionError("overlap across registries was accepted")
    finally:
        first.release()

    second = second_registry.acquire((tmp_path / "workspace" / "nested",), ())
    second.release()

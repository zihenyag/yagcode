"""Process-group lifecycle primitives used only after a verified sandbox launch."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable
from typing import cast

from .base import ProcessHandle, ReconciliationResult, TerminationResult


def _killpg() -> Callable[[int, int], None]:
    kill_process_group = getattr(os, "killpg", None)
    if not callable(kill_process_group):
        raise OSError("PROCESS_GROUP_UNAVAILABLE")
    return cast(Callable[[int, int], None], kill_process_group)


def _signal_number(name: str) -> int:
    value = getattr(signal, name, None)
    if not isinstance(value, int):
        raise OSError("PROCESS_SIGNAL_UNAVAILABLE")
    return int(value)


def reconcile_process(handle: ProcessHandle) -> ReconciliationResult:
    if not handle.started or not isinstance(handle._process, subprocess.Popen):
        return ReconciliationResult("PROCESS_NOT_STARTED", None)
    returncode = handle._process.poll()
    if returncode is None:
        return ReconciliationResult("PROCESS_RUNNING", None)
    return ReconciliationResult("PROCESS_EXITED", returncode)


def terminate_process_tree(handle: ProcessHandle) -> TerminationResult:
    if not handle.started or not isinstance(handle._process, subprocess.Popen) or handle.pid is None:
        return TerminationResult("PROCESS_NOT_STARTED", False)
    pgid = handle.pid

    def group_gone() -> bool:
        try:
            _killpg()(pgid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        return False

    def wait_for_group(deadline: float) -> bool:
        while time.monotonic() < deadline:
            if group_gone():
                return True
            time.sleep(0.02)
        return group_gone()

    try:
        _killpg()(pgid, _signal_number("SIGTERM"))
    except OSError:
        return TerminationResult("PROCESS_TREE_TERMINATION_UNCONFIRMED", False)
    try:
        handle._process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    if wait_for_group(time.monotonic() + 5):
        return TerminationResult("PROCESS_TREE_TERMINATED", True)
    try:
        _killpg()(pgid, _signal_number("SIGKILL"))
    except OSError:
        return TerminationResult("PROCESS_TREE_TERMINATION_UNCONFIRMED", False)
    try:
        handle._process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    if wait_for_group(time.monotonic() + 5):
        return TerminationResult("PROCESS_TREE_TERMINATED", True)
    return TerminationResult("PROCESS_TREE_TERMINATION_UNCONFIRMED", False)

"""Test the callable completeness oracle for the single Windows native probe."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _probe_module() -> object:
    path = Path(__file__).parents[3] / "tests" / "adversarial" / "sandbox" / "native_escape_probe.py"
    spec = importlib.util.spec_from_file_location("native_escape_probe_matrix", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_native_dispatcher_matrix_oracle_rejects_every_missing_behavior() -> None:
    probe = _probe_module()
    complete = set(probe.WINDOWS_DISPATCHER_MATRIX_EVENTS)
    assert probe.windows_dispatcher_matrix_errors(complete) == ()
    for missing in complete:
        assert missing in probe.windows_dispatcher_matrix_errors(complete - {missing})


def test_windows_dacl_snapshot_match_allows_only_auto_inherited_control_noise() -> None:
    probe = _probe_module()
    expected = (b"same-acl", 0x8004)

    assert probe.windows_dacl_snapshot_matches((b"same-acl", 0x8404), expected)
    assert not probe.windows_dacl_snapshot_matches((b"same-acl", 0x9004), expected)
    assert not probe.windows_dacl_snapshot_matches((b"different-acl", 0x8404), expected)

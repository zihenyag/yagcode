"""bounded anti-cheat sensor tests."""

from __future__ import annotations

import importlib

import pytest


def test_owned_anti_cheat_manifest_oracle() -> None:
    before = {"tests/test_guard.py": "sha256:a"}
    after = dict(before)
    assert before == after
    after.pop("tests/test_guard.py")
    assert before != after


def load_feedback_contract():
    try:
        return importlib.import_module("yagcode.tools.anti_cheat")
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.startswith("yagcode.tools"):
            pytest.fail(f"FEEDBACK_CONTRACT_MISSING: {error.name}")
        raise


def test_protected_manifest_detects_deleted_test_skip_config_and_dispatcher_bypass() -> None:
    anti_cheat = load_feedback_contract()
    before = anti_cheat.ProtectedManifest(
        protected_tests=("tests/test_guard.py",),
        skip_markers=(),
        config_hashes={"pyproject.toml": "sha256:a"},
        dispatcher_bypasses=(),
    )
    after = anti_cheat.ProtectedManifest(
        protected_tests=(),
        skip_markers=("xfail",),
        config_hashes={"pyproject.toml": "sha256:b"},
        dispatcher_bypasses=("src/direct_tool.py",),
    )
    violations = anti_cheat.inspect_protected_changes(before, after)
    assert tuple(item.reason_code for item in violations) == (
        "PROTECTED_TEST_DELETED",
        "PROTECTED_CONFIG_CHANGED",
        "DISPATCHER_BYPASS_DETECTED",
        "SKIP_MARKER_ADDED",
    )

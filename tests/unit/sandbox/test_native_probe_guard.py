"""Self-tests for the test-owned native probe guard."""

from __future__ import annotations

import tomllib
from pathlib import Path
import subprocess
import sys

from conftest import NativeProbeReport, platform_deselection_markers, validate_native_probe_reports


def test_owned_native_probe_report_oracle_rejects_every_escape_hatch() -> None:
    valid = (NativeProbeReport("passed", True),)
    assert validate_native_probe_reports(valid) == ()
    assert validate_native_probe_reports(()) == ("NATIVE_PROBE_ZERO_CASES",)
    assert validate_native_probe_reports((NativeProbeReport("skipped", True),)) == (
        "NATIVE_PROBE_SKIP_FORBIDDEN",
    )
    assert validate_native_probe_reports((NativeProbeReport("xfailed", True),)) == (
        "NATIVE_PROBE_XFAIL_FORBIDDEN",
    )
    assert validate_native_probe_reports((NativeProbeReport("xpassed", True),)) == (
        "NATIVE_PROBE_XPASS_FORBIDDEN",
    )
    assert validate_native_probe_reports((NativeProbeReport("passed", False),)) == (
        "NATIVE_PROBE_MARKER_MISMATCH",
    )


def _native_collection_contract_errors(config: dict[str, object]) -> tuple[str, ...]:
    errors: list[str] = []
    if config.get("python_files") != ["test_*.py"]:
        errors.append("NATIVE_PROBE_PYTHON_FILES_DRIFT")
    markers = config.get("markers")
    if not isinstance(markers, list) or not any(
        isinstance(marker, str) and marker.startswith("native_sandbox:") for marker in markers
    ):
        errors.append("NATIVE_PROBE_MARKER_MISSING")
    if "--strict-markers" not in config.get("addopts", ""):
        errors.append("NATIVE_PROBE_STRICT_MARKERS_MISSING")
    return tuple(errors)


def test_owned_native_collection_contract_oracle_rejects_relaxations() -> None:
    valid = {
        "python_files": ["test_*.py"],
        "markers": [
            "native_sandbox: requires the matching host OS sandbox backend",
            "posix_only: requires POSIX descriptor semantics",
            "macos_only: requires the macOS sandbox-exec backend",
        ],
        "addopts": "-ra --strict-markers",
    }
    assert _native_collection_contract_errors(valid) == ()
    for key, value, expected in (
        ("python_files", ["*.py"], "NATIVE_PROBE_PYTHON_FILES_DRIFT"),
        ("markers", [], "NATIVE_PROBE_MARKER_MISSING"),
        ("addopts", "-ra", "NATIVE_PROBE_STRICT_MARKERS_MISSING"),
    ):
        mutated = valid | {key: value}
        assert expected in _native_collection_contract_errors(mutated)


def test_native_collection_contract_matches_repository_configuration() -> None:
    root = Path(__file__).parents[3]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"][
        "ini_options"
    ]
    assert _native_collection_contract_errors(config) == ()


def test_platform_deselection_rules_are_collection_only_and_host_specific() -> None:
    assert platform_deselection_markers("darwin", "posix") == ()
    assert platform_deselection_markers("linux", "posix") == ("macos_only",)
    assert platform_deselection_markers("win32", "nt") == ("posix_only", "macos_only")


def _run_isolated_probe_guard(tmp_path: Path, source: str, conftest_source: str | None = None) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).parents[3]
    tmp_path.mkdir()
    (tmp_path / "conftest.py").write_text(
        (root / "tests" / "conftest.py").read_text() if conftest_source is None else conftest_source,
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-ra --strict-markers'\n"
        "markers = ['native_sandbox: required native probe']\n",
        encoding="utf-8",
    )
    (tmp_path / "test_probe.py").write_text(source, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "-q", "--require-native-probe"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_native_probe_guard_runs_real_pytest_hooks_and_rejects_bypasses(tmp_path: Path) -> None:
    cases = (
        ("import pytest\n@pytest.mark.native_sandbox\ndef test_probe(): assert True\n", 0, None),
        ("def helper(): pass\n", 1, "NATIVE_PROBE_ZERO_CASES"),
        ("import pytest\n@pytest.mark.native_sandbox\ndef test_probe(): pytest.skip('no')\n", 1, "NATIVE_PROBE_SKIP_FORBIDDEN"),
        ("import pytest\n@pytest.mark.native_sandbox\n@pytest.mark.xfail\ndef test_probe(): assert False\n", 1, "NATIVE_PROBE_XFAIL_FORBIDDEN"),
        ("import pytest\n@pytest.mark.native_sandbox\n@pytest.mark.xfail\ndef test_probe(): assert True\n", 1, "NATIVE_PROBE_XPASS_FORBIDDEN"),
        ("def test_probe(): assert True\n", 1, "NATIVE_PROBE_MARKER_MISMATCH"),
    )
    for index, (source, expected, code) in enumerate(cases):
        result = _run_isolated_probe_guard(tmp_path / str(index), source)
        assert result.returncode == expected, result.stdout + result.stderr
        if code is not None:
            assert code in result.stdout + result.stderr


def test_native_probe_guard_mutations_are_detected_by_isolated_pytest(tmp_path: Path) -> None:
    root = Path(__file__).parents[3]
    source = "import pytest\n@pytest.mark.native_sandbox\ndef test_probe(): assert True\n"
    original = (root / "tests" / "conftest.py").read_text(encoding="utf-8")
    no_finish = original.replace("def pytest_sessionfinish", "def removed_sessionfinish", 1)
    skipped = _run_isolated_probe_guard(tmp_path / "finish", "import pytest\n@pytest.mark.native_sandbox\ndef test_probe(): pytest.skip()\n", no_finish)
    assert skipped.returncode == 0
    no_record = original.replace(
        "config._yagcode_native_probe_reports.append(", "if False: config._yagcode_native_probe_reports.append(", 1
    )
    missing = _run_isolated_probe_guard(tmp_path / "record", source, no_record)
    assert missing.returncode != 0
    assert "NATIVE_PROBE_ZERO_CASES" in missing.stdout + missing.stderr

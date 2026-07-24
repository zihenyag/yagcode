"""Test-only native-probe collection guard.

The production sandbox is deliberately not imported here: this guard must be
able to prove its own report interpretation before any backend exists.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import sys
from typing import Literal

import pytest


Outcome = Literal["passed", "failed", "skipped", "xfailed", "xpassed"]


@dataclass(frozen=True, slots=True)
class NativeProbeReport:
    outcome: Outcome
    has_native_marker: bool


@dataclass(frozen=True, slots=True)
class NativeProbeSummary:
    selected: int
    skipped: int
    xfailed: int
    xpassed: int
    marker_mismatch: int
    failed: int


def validate_native_probe_reports(reports: tuple[NativeProbeReport, ...]) -> tuple[str, ...]:
    """Return stable guard failures without consulting pytest or production."""
    selected = len(reports)
    skipped = sum(report.outcome == "skipped" for report in reports)
    xfailed = sum(report.outcome == "xfailed" for report in reports)
    xpassed = sum(report.outcome == "xpassed" for report in reports)
    marker_mismatch = sum(not report.has_native_marker for report in reports)
    failures: list[str] = []
    if selected == 0:
        failures.append("NATIVE_PROBE_ZERO_CASES")
    if skipped:
        failures.append("NATIVE_PROBE_SKIP_FORBIDDEN")
    if xfailed:
        failures.append("NATIVE_PROBE_XFAIL_FORBIDDEN")
    if xpassed:
        failures.append("NATIVE_PROBE_XPASS_FORBIDDEN")
    if marker_mismatch:
        failures.append("NATIVE_PROBE_MARKER_MISMATCH")
    return tuple(failures)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-native-probe",
        action="store_true",
        default=False,
        help="fail if the selected native sandbox probe did not run cleanly",
    )


def pytest_configure(config: pytest.Config) -> None:
    config._yagcode_native_probe_reports = []  # type: ignore[attr-defined]
    config._yagcode_native_probe_mismatches = 0  # type: ignore[attr-defined]


def platform_deselection_markers(
    platform: str = sys.platform,
    os_name: str = os.name,
) -> tuple[str, ...]:
    """Return collection-only platform markers that cannot execute on this host."""

    markers: list[str] = []
    if os_name != "posix":
        markers.append("posix_only")
    if platform != "darwin":
        markers.append("macos_only")
    return tuple(markers)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    blocked_markers = platform_deselection_markers()
    if blocked_markers:
        selected: list[pytest.Item] = []
        deselected: list[pytest.Item] = []
        for item in items:
            if any(item.get_closest_marker(marker) is not None for marker in blocked_markers):
                deselected.append(item)
            else:
                selected.append(item)
        if deselected:
            config.hook.pytest_deselected(items=deselected)
            items[:] = selected
    if not config.getoption("--require-native-probe"):
        return
    config._yagcode_native_probe_mismatches = sum(  # type: ignore[attr-defined]
        item.get_closest_marker("native_sandbox") is None for item in items
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]) -> object:
    outcome = yield
    report = outcome.get_result()
    config = item.config
    if not config.getoption("--require-native-probe"):
        return
    if report.when not in {"setup", "call"}:
        return
    if report.when == "setup" and not report.skipped:
        return
    if report.skipped:
        report_outcome: Outcome = (
            "xfailed"
            if getattr(report, "wasxfail", None) or item.get_closest_marker("xfail") is not None
            else "skipped"
        )
    elif getattr(report, "wasxfail", None) or item.get_closest_marker("xfail") is not None:
        report_outcome = "xpassed" if report.passed else "xfailed"
    elif report.passed:
        report_outcome = "passed"
    else:
        report_outcome = "failed"
    config._yagcode_native_probe_reports.append(  # type: ignore[attr-defined]
        NativeProbeReport(outcome=report_outcome, has_native_marker=True)
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    if not config.getoption("--require-native-probe"):
        return
    reports = tuple(config._yagcode_native_probe_reports)  # type: ignore[attr-defined]
    mismatches = config._yagcode_native_probe_mismatches  # type: ignore[attr-defined]
    failures = list(validate_native_probe_reports(reports))
    if mismatches:
        failures.append("NATIVE_PROBE_MARKER_MISMATCH")
    if failures:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        terminal = config.pluginmanager.get_plugin("terminalreporter")
        if terminal is not None:
            terminal.write_line("; ".join(sorted(set(failures))))

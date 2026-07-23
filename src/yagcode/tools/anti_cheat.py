"""Bounded protected-test/config/dispatcher anti-cheat sensor."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProtectedManifest:
    protected_tests: tuple[str, ...]
    skip_markers: tuple[str, ...]
    config_hashes: Mapping[str, str]
    dispatcher_bypasses: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Violation:
    path: str
    reason_code: str


def inspect_protected_changes(
    before: ProtectedManifest,
    after: ProtectedManifest,
) -> tuple[Violation, ...]:
    violations: list[Violation] = []
    after_tests = set(after.protected_tests)
    for path in before.protected_tests:
        if path not in after_tests:
            violations.append(Violation(path, "PROTECTED_TEST_DELETED"))
    for path, old_hash in before.config_hashes.items():
        if after.config_hashes.get(path) != old_hash:
            violations.append(Violation(path, "PROTECTED_CONFIG_CHANGED"))
    for path in after.dispatcher_bypasses:
        violations.append(Violation(path, "DISPATCHER_BYPASS_DETECTED"))
    before_markers = set(before.skip_markers)
    for marker in after.skip_markers:
        if marker not in before_markers:
            violations.append(Violation(marker, "SKIP_MARKER_ADDED"))
    return tuple(violations)


__all__ = ["ProtectedManifest", "Violation", "inspect_protected_changes"]

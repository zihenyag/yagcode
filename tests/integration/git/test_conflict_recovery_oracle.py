from __future__ import annotations

import importlib

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OwnedObservedEntry:
    matches_preimage: bool
    matches_verified_postimage: bool
    matches_owned_postimage: bool
    compensation_preconditions_hold: bool


def owned_classify(entries: tuple[OwnedObservedEntry, ...]) -> str:
    if not entries:
        return "MIXED_OR_UNKNOWN"
    if all(entry.matches_preimage for entry in entries):
        return "ALL_PREIMAGE"
    if all(entry.matches_verified_postimage for entry in entries):
        return "ALL_POSTIMAGE"
    if all(
        entry.matches_preimage
        or (entry.matches_owned_postimage and entry.compensation_preconditions_hold)
        for entry in entries
    ):
        return "OWNED_POSTIMAGE_COMPENSATABLE"
    return "MIXED_OR_UNKNOWN"


def test_owned_recovery_oracle_classifies_all_required_branches() -> None:
    assert owned_classify((OwnedObservedEntry(True, False, False, False),)) == "ALL_PREIMAGE"
    assert owned_classify((OwnedObservedEntry(False, True, True, False),)) == "ALL_POSTIMAGE"
    assert (
        owned_classify(
            (
                OwnedObservedEntry(True, False, False, False),
                OwnedObservedEntry(False, False, True, True),
            )
        )
        == "OWNED_POSTIMAGE_COMPENSATABLE"
    )
    assert owned_classify((OwnedObservedEntry(False, False, True, False),)) == "MIXED_OR_UNKNOWN"


def test_owned_recovery_oracle_rejects_journal_self_report() -> None:
    journal_claims_safe = OwnedObservedEntry(
        matches_preimage=False,
        matches_verified_postimage=False,
        matches_owned_postimage=True,
        compensation_preconditions_hold=False,
    )
    assert owned_classify((journal_claims_safe,)) == "MIXED_OR_UNKNOWN"


def test_owned_recovery_oracle_empty_input_is_unknown() -> None:
    assert owned_classify(()) == "MIXED_OR_UNKNOWN"


def test_production_recovery_classification_matches_oracle() -> None:
    recovery = importlib.import_module("yagcode.git.recovery")
    states = importlib.import_module("yagcode.domain.states")
    entries = (
        recovery.ObservedIntegrationEntry(
            matches_preimage=True,
            matches_verified_postimage=False,
            matches_owned_postimage=False,
            compensation_preconditions_hold=False,
        ),
        recovery.ObservedIntegrationEntry(
            matches_preimage=False,
            matches_verified_postimage=False,
            matches_owned_postimage=True,
            compensation_preconditions_hold=True,
        ),
    )
    assert recovery.classify_recovery(entries) is states.RecoveryClass.OWNED_POSTIMAGE_COMPENSATABLE

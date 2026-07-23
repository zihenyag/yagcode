"""Recovery classification based on observed filesystem state, not journal claims."""

from __future__ import annotations

from dataclasses import dataclass

from yagcode.domain.states import RecoveryClass


@dataclass(frozen=True, slots=True)
class ObservedIntegrationEntry:
    matches_preimage: bool
    matches_verified_postimage: bool
    matches_owned_postimage: bool
    compensation_preconditions_hold: bool

    def __post_init__(self) -> None:
        if not all(
            type(value) is bool
            for value in (
                self.matches_preimage,
                self.matches_verified_postimage,
                self.matches_owned_postimage,
                self.compensation_preconditions_hold,
            )
        ):
            raise TypeError("OBSERVED_ENTRY_BOOL_REQUIRED")


def classify_recovery(entries: tuple[ObservedIntegrationEntry, ...]) -> RecoveryClass:
    if not entries:
        return RecoveryClass.MIXED_OR_UNKNOWN
    if all(entry.matches_preimage for entry in entries):
        return RecoveryClass.ALL_PREIMAGE
    if all(entry.matches_verified_postimage for entry in entries):
        return RecoveryClass.ALL_POSTIMAGE
    if all(
        entry.matches_preimage
        or (entry.matches_owned_postimage and entry.compensation_preconditions_hold)
        for entry in entries
    ):
        return RecoveryClass.OWNED_POSTIMAGE_COMPENSATABLE
    return RecoveryClass.MIXED_OR_UNKNOWN


__all__ = ["ObservedIntegrationEntry", "classify_recovery"]

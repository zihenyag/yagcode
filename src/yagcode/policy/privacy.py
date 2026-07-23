"""Privacy grants, preview decisions, and retention policy helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _text(name: str, value: object) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise ValueError(f"PRIVACY_{name}_INVALID")
    return value


@dataclass(frozen=True, slots=True)
class PrivacyGrantKey:
    profile_id: str
    canonical_source_scope: str
    category: str
    purpose: str
    recipient_set_version: int

    def __post_init__(self) -> None:
        _text("PROFILE", self.profile_id)
        _text("SOURCE", self.canonical_source_scope)
        _text("CATEGORY", self.category)
        _text("PURPOSE", self.purpose)
        if self.recipient_set_version < 0:
            raise ValueError("PRIVACY_RECIPIENT_SET_VERSION_INVALID")


@dataclass(frozen=True, slots=True)
class PrivacyGrant:
    key: PrivacyGrantKey
    granted_at: datetime


@dataclass(frozen=True, slots=True)
class PrivacyDecision:
    allowed: bool
    preview_required: bool
    reason_code: str


class PrivacyGuard:
    def __init__(self, *, current_recipient_set_version: int, clock: Clock = _default_clock) -> None:
        self.current_recipient_set_version = current_recipient_set_version
        self._clock = clock
        self._grants: set[PrivacyGrantKey] = set()

    def grant(
        self,
        profile_id: str,
        canonical_source_scope: str,
        category: str,
        purpose: str,
        recipient_set_version: int,
    ) -> PrivacyGrant:
        key = PrivacyGrantKey(
            profile_id,
            canonical_source_scope,
            category,
            purpose,
            recipient_set_version,
        )
        self._grants.add(key)
        return PrivacyGrant(key, self._clock())

    def matches(
        self,
        grant: PrivacyGrant,
        *,
        profile_id: str,
        provider: str,
        source: str,
        category: str,
        purpose: str,
        recipient_set_version: int | None = None,
    ) -> bool:
        _text("PROVIDER", provider)
        version = self.current_recipient_set_version if recipient_set_version is None else recipient_set_version
        key = PrivacyGrantKey(profile_id, source, category, purpose, version)
        if category == "secret" or "/secrets/" in source or source.endswith("/secrets"):
            return False
        return grant.key == key and key in self._grants

    def require_grant_or_preview(
        self,
        profile_id: str,
        provider: str,
        source: str,
        category: str,
        purpose: str,
    ) -> PrivacyDecision:
        _text("PROVIDER", provider)
        if category == "secret" or "/secrets/" in source or source.endswith("/secrets"):
            return PrivacyDecision(False, False, "SECRET_SCOPE_DENIED")
        key = PrivacyGrantKey(
            profile_id,
            source,
            category,
            purpose,
            self.current_recipient_set_version,
        )
        if key in self._grants:
            return PrivacyDecision(True, False, "PRIVACY_GRANT_MATCHED")
        return PrivacyDecision(False, True, "PRIVACY_PREVIEW_REQUIRED")


@dataclass(frozen=True, slots=True)
class RetentionRecord:
    profile_id: str
    category: str
    retention: str
    value: str
    created_at: datetime


class RetentionService:
    _DAYS = {
        "30d": 30,
        "60d": 60,
        "90d": 90,
        "180d": 180,
        "1y": 365,
        "2y": 730,
    }

    def __init__(self, *, clock: Clock = _default_clock) -> None:
        self._clock = clock
        self._records: list[RetentionRecord] = []

    def record(self, profile_id: str, category: str, retention: str, value: str) -> None:
        _text("PROFILE", profile_id)
        _text("CATEGORY", category)
        _text("RETENTION", retention)
        if retention != "permanent" and retention not in self._DAYS:
            raise ValueError("RETENTION_POLICY_INVALID")
        if category in {"privacy_preview", "audit"} and retention != "permanent":
            raise ValueError("RETENTION_PERMANENT_REQUIRED")
        self._records.append(RetentionRecord(profile_id, category, retention, value, self._clock()))

    def cleanup(self) -> None:
        now = self._clock()
        kept: list[RetentionRecord] = []
        for record in self._records:
            if record.retention == "permanent":
                kept.append(record)
                continue
            if now - record.created_at <= timedelta(days=self._DAYS[record.retention]):
                kept.append(record)
        self._records = kept

    def values(self, profile_id: str) -> tuple[str, ...]:
        return tuple(record.value for record in self._records if record.profile_id == profile_id)

    def delete_profile(self, profile_id: str) -> None:
        self._records = [record for record in self._records if record.profile_id != profile_id]


__all__ = [
    "PrivacyDecision",
    "PrivacyGrant",
    "PrivacyGrantKey",
    "PrivacyGuard",
    "RetentionRecord",
    "RetentionService",
]

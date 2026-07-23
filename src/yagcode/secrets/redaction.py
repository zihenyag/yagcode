"""Central redaction before log, UI, artifact, audit, or crash output."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from yagcode.domain.actions import JsonValue


@dataclass(frozen=True, slots=True)
class RedactionFailure:
    reason_code: Literal["REDACTION_KEY_COLLISION", "REDACTION_INPUT_UNSAFE"]


class SecretRegistry:
    def __init__(self) -> None:
        self._secrets: tuple[str, ...] = ()

    def register(self, secret_value: str) -> None:
        if type(secret_value) is not str or secret_value == "":
            raise ValueError("SECRET_EMPTY")
        if "\x00" in secret_value:
            raise ValueError("SECRET_INVALID")
        if secret_value not in self._secrets:
            self._secrets = (*self._secrets, secret_value)

    def redact_text(self, value: str) -> str:
        redacted = value
        for secret_value in self._secrets:
            redacted = redacted.replace(secret_value, "[REDACTED]")
        return redacted


def _safe_string(value: str, registry: SecretRegistry) -> str:
    return registry.redact_text(value)


def _redact_exception(value: BaseException, registry: SecretRegistry) -> dict[str, JsonValue]:
    return {
        "type": type(value).__name__,
        "message": "[EXCEPTION_REDACTED]",
        "redacted": True,
    }


def _redact(value: object, registry: SecretRegistry) -> JsonValue | RedactionFailure:
    if value is None or type(value) in {bool, int, float}:
        return value  # type: ignore[return-value]
    if type(value) is str:
        return _safe_string(value, registry)
    if type(value) is bytes:
        return "[BYTES_REDACTED]"
    if isinstance(value, BaseException):
        return _redact_exception(value, registry)
    if isinstance(value, Mapping):
        output: dict[str, JsonValue] = {}
        for key, item in value.items():
            key_text = key if type(key) is str else "[NON_STRING_KEY]"
            safe_key = _safe_string(key_text, registry)
            if safe_key in output:
                return RedactionFailure("REDACTION_KEY_COLLISION")
            safe_value = _redact(item, registry)
            if isinstance(safe_value, RedactionFailure):
                return safe_value
            output[safe_key] = safe_value
        return output
    if isinstance(value, tuple):
        output_items: list[JsonValue] = []
        for item in value:
            safe_item = _redact(item, registry)
            if isinstance(safe_item, RedactionFailure):
                return safe_item
            output_items.append(safe_item)
        return output_items
    if isinstance(value, list):
        output_items = []
        for item in value:
            safe_item = _redact(item, registry)
            if isinstance(safe_item, RedactionFailure):
                return safe_item
            output_items.append(safe_item)
        return output_items
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[SEQUENCE_REDACTED]"
    return "[OBJECT_REDACTED]"


def redact_for_output(value: object, registry: SecretRegistry) -> JsonValue | RedactionFailure:
    return _redact(value, registry)


__all__ = ["RedactionFailure", "SecretRegistry", "redact_for_output"]

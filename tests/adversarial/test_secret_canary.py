"""Canaries must never survive centralized output redaction."""

from __future__ import annotations

import importlib


class _CanaryObject:
    def __str__(self) -> str:
        return "CANARY-secret-value"

    def __repr__(self) -> str:
        return "CANARY-secret-value"


def _walk(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(_walk(key) + _walk(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return " ".join(_walk(item) for item in value)
    return str(value)


def test_owned_canary_walker_detects_nested_values() -> None:
    assert "CANARY" in _walk({"x": ["CANARY-secret-value"]})
    assert "CANARY" not in _walk({"x": ["[REDACTED]"]})


def test_redaction_removes_canaries_from_all_supported_output_shapes() -> None:
    production = importlib.import_module("yagcode.secrets.redaction")
    registry = production.SecretRegistry()
    registry.register("CANARY-secret-value")
    error = RuntimeError("CANARY-secret-value")
    error.__cause__ = ValueError("CANARY-secret-value")
    payload = {
        "CANARY-secret-value": "CANARY-secret-value",
        "nested": ["CANARY-secret-value", (b"CANARY-secret-value", _CanaryObject())],
        "error": error,
    }
    output = production.redact_for_output(payload, registry)
    assert "CANARY" not in _walk(output)
    assert payload["CANARY-secret-value"] == "CANARY-secret-value"


def test_empty_secret_is_rejected_and_key_collision_fails_closed() -> None:
    production = importlib.import_module("yagcode.secrets.redaction")
    registry = production.SecretRegistry()
    try:
        registry.register("")
    except ValueError as error:
        assert str(error) == "SECRET_EMPTY"
    else:
        raise AssertionError("empty secret accepted")
    registry.register("a")
    failed = production.redact_for_output({"a": 1, "[REDACTED]": 2}, registry)
    assert failed.reason_code == "REDACTION_KEY_COLLISION"

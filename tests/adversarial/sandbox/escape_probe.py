"""Adversarial path escape remains safe even after alias replacement."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _production() -> object:
    try:
        return importlib.import_module("yagcode.policy.paths")
    except ModuleNotFoundError as error:
        if error.name == "yagcode.policy.paths":
            pytest.fail("TRUSTED_PATH_CONTRACT_MISSING")
        raise


def test_symlink_switch_cannot_redirect_a_verified_write(tmp_path: Path) -> None:
    production = _production()
    trusted = tmp_path / "trusted"
    protected = tmp_path / "protected"
    trusted.mkdir()
    protected.mkdir()
    candidate = trusted / "candidate"
    candidate.write_bytes(b"before")
    resolver = production.SecurePathResolver(tmp_path)
    target = resolver.resolve_for_write(candidate)
    candidate.unlink()
    candidate.symlink_to(protected / "canary")

    assert production.SecurePathDispatcher(resolver).write(target, b"blocked").reason == "STALE_TARGET"
    assert not (protected / "canary").exists()

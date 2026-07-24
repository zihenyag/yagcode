"""Trusted-path contracts; production is deliberately loaded at test runtime."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.posix_only


def _paths_production() -> object:
    try:
        return importlib.import_module("yagcode.policy.paths")
    except ModuleNotFoundError as error:
        if error.name == "yagcode.policy.paths":
            pytest.fail("TRUSTED_PATH_CONTRACT_MISSING")
        raise


def test_owned_path_snapshot_oracle_detects_replacement() -> None:
    before = ("root:1", "safe:2", "link:3")
    same = ("root:1", "safe:2", "link:3")
    replaced = ("root:1", "safe:2", "link:4")
    assert before == same
    assert before != replaced


def test_replaced_symlink_invalidates_resolved_target(tmp_path: Path) -> None:
    production = _paths_production()
    safe = tmp_path / "safe"
    outside = tmp_path / "outside"
    safe.mkdir()
    outside.mkdir()
    link = safe / "target"
    link.write_bytes(b"before")

    resolver = production.SecurePathResolver(tmp_path)
    dispatcher = production.SecurePathDispatcher(resolver)
    resolved = resolver.resolve_for_write(link)
    link.unlink()
    link.symlink_to(outside / "stolen")

    result = dispatcher.write(resolved, b"x")
    assert result.reason == "STALE_TARGET"
    assert not (outside / "stolen").exists()


def test_parent_symlink_is_never_authorized_for_write(tmp_path: Path) -> None:
    production = _paths_production()
    trusted = tmp_path / "trusted"
    outside = tmp_path / "outside"
    trusted.mkdir()
    outside.mkdir()
    (trusted / "jump").symlink_to(outside, target_is_directory=True)
    resolver = production.SecurePathResolver(trusted)

    with pytest.raises(production.PathSecurityError, match="UNSAFE_PATH"):
        resolver.resolve_for_write(trusted / "jump" / "stolen")
    assert not (outside / "stolen").exists()


def test_terminal_symlink_alias_is_rejected_before_any_write(tmp_path: Path) -> None:
    production = _paths_production()
    trusted = tmp_path / "trusted"
    safe = trusted / "safe"
    trusted.mkdir()
    safe.mkdir()
    written = safe / "written"
    written.write_bytes(b"before")
    alias = trusted / "alias"
    alias.symlink_to(written)

    with pytest.raises(production.PathSecurityError, match="UNSAFE_PATH_SYMLINK_COMPONENT"):
        production.SecurePathResolver(trusted).resolve_for_write(alias)
    assert written.read_bytes() == b"before"


def test_lexical_parent_component_is_rejected_before_resolution(tmp_path: Path) -> None:
    production = _paths_production()
    trusted = tmp_path / "trusted"
    outside = tmp_path / "outside"
    trusted.mkdir()
    outside.mkdir()

    with pytest.raises(production.PathSecurityError, match="UNSAFE_PATH_COMPONENT_INVALID"):
        production.SecurePathResolver(trusted).resolve_for_write(Path("..") / "outside" / "stolen")
    assert not (outside / "stolen").exists()


def test_hard_link_alias_outside_root_is_never_modified(tmp_path: Path) -> None:
    production = _paths_production()
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside-before")
    linked = trusted / "linked.txt"
    linked.hardlink_to(outside)
    resolver = production.SecurePathResolver(trusted)

    with pytest.raises(production.PathSecurityError, match="UNSAFE_PATH_HARDLINK_TARGET"):
        resolver.resolve_for_write(linked)
    assert outside.read_bytes() == b"outside-before"


def test_missing_target_is_created_through_the_verified_parent_descriptor(tmp_path: Path) -> None:
    production = _paths_production()
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    resolver = production.SecurePathResolver(trusted)
    target = resolver.resolve_for_write(trusted / "new.txt")

    assert production.SecurePathDispatcher(resolver).write(target, b"created").reason == "WRITTEN"
    assert (trusted / "new.txt").read_bytes() == b"created"

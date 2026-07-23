"""Dependency placeholders for later workflow routes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Services:
    profile_id: str = "default"


def get_services() -> Services:
    return Services()


__all__ = ["Services", "get_services"]

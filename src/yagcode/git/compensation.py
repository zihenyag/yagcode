"""Compensation primitives for accepted-change rollback."""

from __future__ import annotations


class CompensationError(RuntimeError):
    """A live target no longer matches the postimage owned by this accept run."""


__all__ = ["CompensationError"]

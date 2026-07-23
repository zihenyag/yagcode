"""Conventional Commit validation for user-confirmed local commits."""

from __future__ import annotations

import re


CONVENTIONAL_COMMIT = re.compile(
    r"^(feat|fix|docs|test|refactor|perf|build|ci|chore)(\([a-z0-9-]+\))?!?: [a-z0-9].{0,71}$"
)


def is_conventional_commit(message: str) -> bool:
    return type(message) is str and CONVENTIONAL_COMMIT.fullmatch(message) is not None


__all__ = ["CONVENTIONAL_COMMIT", "is_conventional_commit"]

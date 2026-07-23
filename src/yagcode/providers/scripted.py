"""Deterministic scripted Provider used by tests and later loop demos."""

from __future__ import annotations

from collections.abc import Mapping

from .base import ProviderContext, ProviderFailure, ProviderResult


class ScriptedProvider:
    def __init__(self, provider_id: str, branches: Mapping[tuple[str, ...], object]) -> None:
        self.provider_id = provider_id
        self._branches = dict(branches)

    def complete_once(self, context: ProviderContext) -> ProviderResult | ProviderFailure:
        candidate = self._branches.get(context.feedback_codes)
        if candidate is None:
            candidate = self._branches.get((), {"kind": "request_review"})
        return ProviderResult.from_candidate(
            self.provider_id,
            context.model,
            context.generation,
            candidate,
        )


__all__ = ["ScriptedProvider"]

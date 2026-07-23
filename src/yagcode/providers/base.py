"""Single-call Provider contract and JSON-domain normalization."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from yagcode.domain.actions import JsonValue


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderContext:
    run_id: str
    generation: int
    provider: str
    model: str
    feedback_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    provider: str
    model: str
    generation: int
    error_code: str


@dataclass(frozen=True, slots=True)
class ProviderResult:
    provider: str
    model: str
    generation: int
    action_candidate: JsonValue
    candidate_count: Literal[1]
    usage: Usage | None
    cost: Decimal | None

    @classmethod
    def from_candidate(
        cls,
        provider: str,
        model: str,
        generation: int,
        candidate: object,
        *,
        usage: Usage | None = None,
        cost: Decimal | None = None,
    ) -> ProviderResult | ProviderFailure:
        if not _is_json_domain(candidate):
            return ProviderFailure(provider, model, generation, "PROVIDER_RESPONSE_JSON_DOMAIN_INVALID")
        return cls(provider, model, generation, _copy_json(candidate), 1, usage, cost)


class Provider(Protocol):
    provider_id: str

    def complete_once(self, context: ProviderContext) -> ProviderResult | ProviderFailure: ...


def _is_json_domain(value: object) -> bool:
    if value is None or type(value) in {bool, int, str}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_is_json_domain(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _is_json_domain(item) for key, item in value.items())
    return False


def _copy_json(value: object) -> JsonValue:
    return copy.deepcopy(value)  # type: ignore[return-value]


__all__ = [
    "Provider",
    "ProviderContext",
    "ProviderFailure",
    "ProviderResult",
    "Usage",
]

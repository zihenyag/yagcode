"""Provider contracts and fixture adapters for governed single-call completion."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import deepseek, glm, openai, qwen
from .base import Provider, ProviderContext, ProviderFailure, ProviderResult, Usage
from .scripted import ScriptedProvider


@dataclass(frozen=True, slots=True)
class OfficialEndpoint:
    method: str
    url: str
    docs_url: str
    retrieved_at: str


class FixtureAdapter:
    """Strict decoded-response adapter used by deterministic contract tests."""

    def __init__(
        self,
        provider_id: str,
        decoded_response: dict[str, object],
        extractor: Callable[[dict[str, object]], object],
    ) -> None:
        self.provider_id = provider_id
        self.decoded_response = copy.deepcopy(decoded_response)
        self._extractor = extractor

    def complete_once(self, context: ProviderContext) -> ProviderResult | ProviderFailure:
        try:
            candidate = self._extractor(self.decoded_response)
        except ValueError as error:
            return ProviderFailure(
                self.provider_id,
                context.model,
                context.generation,
                str(error),
            )
        return ProviderResult.from_candidate(
            self.provider_id,
            context.model,
            context.generation,
            candidate,
            usage=_usage_from_decoded_response(self.decoded_response),
        )


def load_official_endpoints() -> dict[str, OfficialEndpoint]:
    raw = json.loads(Path(__file__).with_name("official_endpoints.json").read_text())
    if type(raw) is not dict:
        raise ValueError("PROVIDER_MANIFEST_INVALID")
    retrieved_at = _text(raw.get("retrieved_at"), "PROVIDER_MANIFEST_RETRIEVED_AT_INVALID")
    providers = raw.get("providers")
    if type(providers) is not dict:
        raise ValueError("PROVIDER_MANIFEST_PROVIDERS_INVALID")
    manifest: dict[str, OfficialEndpoint] = {}
    for provider_id, value in providers.items():
        if type(provider_id) is not str or type(value) is not dict:
            raise ValueError("PROVIDER_MANIFEST_ENTRY_INVALID")
        manifest[provider_id] = OfficialEndpoint(
            method=_text(value.get("method"), "PROVIDER_METHOD_INVALID"),
            url=_text(value.get("url"), "PROVIDER_URL_INVALID"),
            docs_url=_text(value.get("docs_url"), "PROVIDER_DOCS_URL_INVALID"),
            retrieved_at=retrieved_at,
        )
    return manifest


def adapter_for_fixture(provider_id: str, decoded_response: dict[str, object]) -> FixtureAdapter:
    extractors: dict[str, Callable[[dict[str, object]], object]] = {
        "openai": openai.extract_candidate,
        "qwen": qwen.extract_candidate,
        "glm": glm.extract_candidate,
        "deepseek": deepseek.extract_candidate,
    }
    try:
        extractor = extractors[provider_id]
    except KeyError as error:
        raise ValueError("PROVIDER_UNKNOWN") from error
    return FixtureAdapter(provider_id, decoded_response, extractor)


def _usage_from_decoded_response(decoded_response: dict[str, object]) -> Usage | None:
    usage = decoded_response.get("usage")
    if type(usage) is not dict:
        return None
    return Usage(
        input_tokens=_optional_int(usage.get("input_tokens", usage.get("prompt_tokens"))),
        output_tokens=_optional_int(usage.get("output_tokens", usage.get("completion_tokens"))),
        total_tokens=_optional_int(usage.get("total_tokens")),
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is int and value >= 0:
        return value
    return None


def _text(value: object, reason: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise ValueError(reason)
    return value


__all__ = [
    "FixtureAdapter",
    "OfficialEndpoint",
    "Provider",
    "ProviderContext",
    "ProviderFailure",
    "ProviderResult",
    "ScriptedProvider",
    "Usage",
    "adapter_for_fixture",
    "load_official_endpoints",
]

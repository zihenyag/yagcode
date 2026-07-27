"""Provider contract tests with runtime production loading."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from yagcode.domain.action_parser import ActionParseSuccess, ActionParser


VALID_ACTION = {
    "kind": "request_review",
    "action_id": "review-1",
    "run_id": "run-1",
    "generation": 0,
    "reason_summary": "review candidate",
    "payload": {"summary": "ready", "uncovered": []},
}


def test_owned_json_domain_oracle_and_parser_boundary() -> None:
    valid_values = [None, True, 1, 1.5, "x", ["x"], {"candidate": VALID_ACTION}]
    assert all(_is_test_json(value) for value in valid_values)
    invalid_values = [float("nan"), float("inf"), b"x", {1: "bad"}, object()]
    assert not any(_is_test_json(value) for value in invalid_values)
    assert isinstance(ActionParser().parse(VALID_ACTION), ActionParseSuccess)
    assert not isinstance(ActionParser().parse(["not", "an", "object"]), ActionParseSuccess)


def _is_test_json(value: object) -> bool:
    if value is None or type(value) in {bool, int, str}:
        return True
    if type(value) is float:
        return value == value and value not in {float("inf"), float("-inf")}
    if type(value) is list:
        return all(_is_test_json(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _is_test_json(item) for key, item in value.items())
    return False


def load_provider_contract():
    try:
        return importlib.import_module("yagcode.providers")
    except ModuleNotFoundError as error:
        pytest.fail(f"PROVIDER_CONTRACT_MISSING: {error.name}")


def test_official_endpoint_manifest_is_locked() -> None:
    providers = load_provider_contract()
    manifest = providers.load_official_endpoints()
    assert manifest["openai"].method == "POST"
    assert manifest["openai"].url == "https://api.openai.com/v1/responses"
    assert manifest["qwen"].url == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert manifest["glm"].url == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert manifest["deepseek"].url == "https://api.deepseek.com/chat/completions"
    assert manifest["minimax"].url == "https://api.minimax.chat/v1/chat/completions"
    assert manifest["kimi"].url == "https://api.moonshot.cn/v1/chat/completions"
    assert manifest["njusehub"].url == "https://njusehub.info/v1/chat/completions"
    assert manifest["njusehub"].docs_url == "https://dongshao.github.io/GAIHub1/njusehubdoc.html"
    assert all(item.docs_url.startswith("https://") for item in manifest.values())
    raw = json.loads(Path("src/yagcode/providers/official_endpoints.json").read_text())
    assert set(raw["providers"]) == {"openai", "qwen", "glm", "deepseek", "minimax", "kimi", "njusehub"}


@pytest.mark.parametrize("provider_id", ["openai", "qwen", "glm", "deepseek", "minimax", "kimi", "njusehub"])
def test_adapter_returns_one_defensively_copied_candidate(provider_id: str) -> None:
    providers = load_provider_contract()
    adapter = providers.adapter_for_fixture(provider_id, _provider_response(provider_id, VALID_ACTION))
    result = adapter.complete_once(providers.ProviderContext("run-1", 0, provider_id, "model-x", ()))
    assert result.provider == provider_id
    assert result.candidate_count == 1
    assert result.action_candidate == VALID_ACTION
    assert isinstance(ActionParser().parse(result.action_candidate), ActionParseSuccess)
    # Mutating the original decoded response after construction must not mutate ProviderResult.
    _mutate_candidate(_provider_candidate_ref(adapter.decoded_response, provider_id))
    assert result.action_candidate == VALID_ACTION


@pytest.mark.parametrize("candidate", [None, True, 1, "x", ["x"], {"wrapper": VALID_ACTION}])
def test_provider_boundary_preserves_non_object_json_values(candidate: object) -> None:
    providers = load_provider_contract()
    result = providers.ProviderResult.from_candidate("openai", "m", 0, candidate)
    assert result.action_candidate == candidate
    assert result.candidate_count == 1


@pytest.mark.parametrize("candidate", [float("nan"), float("inf"), b"x", {1: "bad"}, object()])
def test_provider_boundary_rejects_non_json_domain_values(candidate: object) -> None:
    providers = load_provider_contract()
    failure = providers.ProviderResult.from_candidate("openai", "m", 0, candidate)
    assert failure.error_code == "PROVIDER_RESPONSE_JSON_DOMAIN_INVALID"


def _provider_response(provider_id: str, candidate: object) -> dict[str, object]:
    if provider_id == "openai":
        return {"output": [{"content": [{"json": candidate}]}], "usage": {"input_tokens": 1}}
    return {"choices": [{"message": {"content": candidate}}], "usage": {"prompt_tokens": 1}}


def _provider_candidate_ref(response: dict[str, object], provider_id: str) -> object:
    if provider_id == "openai":
        return response["output"][0]["content"][0]["json"]  # type: ignore[index]
    return response["choices"][0]["message"]["content"]  # type: ignore[index]


def _mutate_candidate(candidate: object) -> None:
    if isinstance(candidate, dict):
        candidate["payload"] = {"summary": "mutated", "uncovered": []}

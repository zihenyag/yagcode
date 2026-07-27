from __future__ import annotations

import json
import urllib.error

from datetime import UTC, datetime
from typing import Any

from yagcode.providers import ProviderContext, load_official_endpoints
from yagcode.providers.runtime_http import HttpJsonActionProvider
from yagcode.secrets import CredentialBroker


VALID_REVIEW = {
    "kind": "request_review",
    "action_id": "review-1",
    "run_id": "run-1",
    "generation": 0,
    "reason_summary": "ready",
    "payload": {"summary": "ready", "uncovered": []},
}


class _Keyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


class _Response:
    def __init__(self, status_code: int, body: dict[str, object]) -> None:
        self.status_code = status_code
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status_code

    def read(self) -> bytes:
        return self.body


class _Urlopen:
    def __init__(self, responses: list[_Response | BaseException]) -> None:
        self.responses = responses
        self.requests: list[Any] = []

    def __call__(self, request: Any, *, timeout: float) -> _Response:
        del timeout
        self.requests.append(request)
        next_response = self.responses.pop(0)
        if isinstance(next_response, BaseException):
            raise next_response
        return next_response


def _broker() -> CredentialBroker:
    return CredentialBroker(
        _Keyring(),
        clock=lambda: datetime(2026, 7, 26, tzinfo=UTC),
    )


def test_chat_compatible_provider_posts_prompt_with_bearer_header_and_decodes_json_string() -> None:
    broker = _broker()
    broker.enroll("default", "njusehub", "unit-provider-key")
    urlopen = _Urlopen([_Response(200, {"choices": [{"message": {"content": json.dumps(VALID_REVIEW)}}]})])
    provider = HttpJsonActionProvider(
        endpoints=load_official_endpoints(),
        credentials=broker,
        profile_id="default",
        urlopen=urlopen,
    )

    result = provider.complete_once(
        ProviderContext("run-1", 0, "njusehub", "qwen-turbo", (), prompt="fix the bug")
    )

    assert result.action_candidate == VALID_REVIEW
    request = urlopen.requests[0]
    assert request.full_url == "https://njusehub.info/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer unit-provider-key"
    body = json.loads(request.data.decode("utf-8"))
    assert body["model"] == "qwen-turbo"
    assert body["messages"][1]["content"] == "fix the bug"
    assert "unit-provider-key" not in request.data.decode("utf-8")


def test_openai_responses_provider_decodes_output_text_json() -> None:
    broker = _broker()
    broker.enroll("default", "openai", "unit-provider-key")
    urlopen = _Urlopen(
        [
            _Response(
                200,
                {
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": json.dumps(VALID_REVIEW)}],
                        }
                    ],
                    "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
                },
            )
        ]
    )
    provider = HttpJsonActionProvider(
        endpoints=load_official_endpoints(),
        credentials=broker,
        profile_id="default",
        urlopen=urlopen,
    )

    result = provider.complete_once(
        ProviderContext("run-1", 0, "openai", "gpt-5.6-sol", (), prompt="fix the bug")
    )

    assert result.action_candidate == VALID_REVIEW
    assert result.usage is not None
    assert result.usage.total_tokens == 5


def test_runtime_provider_retries_429_and_reports_no_side_effect_failure() -> None:
    broker = _broker()
    broker.enroll("default", "njusehub", "unit-provider-key")
    urlopen = _Urlopen([_http_error(429) for _ in range(6)])
    provider = HttpJsonActionProvider(
        endpoints=load_official_endpoints(),
        credentials=broker,
        profile_id="default",
        urlopen=urlopen,
        max_retries=5,
    )

    result = provider.complete_once(ProviderContext("run-1", 0, "njusehub", "qwen-turbo", ()))

    assert result.error_code == "PROVIDER_HTTP_429"
    assert len(urlopen.requests) == 6


def _http_error(status_code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://provider.invalid/v1/chat/completions",
        status_code,
        "error",
        hdrs=None,
        fp=None,
    )

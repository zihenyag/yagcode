from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_owned_privileged_oracle_requires_main_principal() -> None:
    intent = {"intent_id": "intent-1", "one_time_token": "token"}
    renderer_headers = {"Origin": "app://yagcode"}
    main_headers = {"X-Yagcode-Principal": "main"}
    assert "X-Yagcode-Principal" not in renderer_headers
    assert main_headers["X-Yagcode-Principal"] == "main"
    assert intent["one_time_token"] != intent["intent_id"]


def _client() -> TestClient:
    app_mod = importlib.import_module("yagcode.api.app")
    dependencies = importlib.import_module("yagcode.api.dependencies")
    runtime = app_mod.Runtime(startup_token="startup", desktop_origin="app://yagcode")
    return TestClient(app_mod.create_app(runtime, services=dependencies.Services()))


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer startup", "Origin": "app://yagcode"}


def test_renderer_cannot_directly_accept_or_clear_key() -> None:
    client = _client()

    accept = client.post("/api/v1/review/r1/accept", headers=_headers())
    clear = client.delete("/api/v1/credentials/openai", headers=_headers())

    assert accept.status_code == 403
    assert accept.json()["detail"]["reason_code"] == "MAIN_PRINCIPAL_REQUIRED"
    assert clear.status_code == 403
    assert clear.json()["detail"]["reason_code"] == "MAIN_PRINCIPAL_REQUIRED"


def test_privileged_actions_use_intent_challenge_and_main_consume() -> None:
    client = _client()
    challenge = client.post("/api/v1/review/r1/accept-intent", headers=_headers()).json()
    renderer_consume = client.post(
        f"/api/v1/intents/{challenge['intent_id']}/consume",
        headers=_headers(),
        json={"one_time_token": challenge["one_time_token"]},
    )
    main_consume = client.post(
        f"/api/v1/intents/{challenge['intent_id']}/consume",
        headers={**_headers(), "X-Yagcode-Principal": "main"},
        json={"one_time_token": challenge["one_time_token"]},
    )

    assert challenge["intent_type"] == "ACCEPT_REVIEW"
    assert renderer_consume.status_code == 403
    assert main_consume.status_code == 200
    assert main_consume.json()["state"] == "EXECUTED"

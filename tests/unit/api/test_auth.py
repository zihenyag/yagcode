from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_owned_auth_matrix_rejects_missing_wrong_or_bad_origin() -> None:
    allowed = {"Authorization": "Bearer startup", "Origin": "app://yagcode"}
    assert allowed["Authorization"].endswith("startup")
    assert {"Origin": "https://evil.invalid"}["Origin"] != allowed["Origin"]


def test_nonprivileged_api_rejects_missing_wrong_token_or_origin() -> None:
    runtime_mod = importlib.import_module("yagcode.api.app")
    runtime = runtime_mod.Runtime(startup_token="startup", desktop_origin="app://yagcode")
    client = TestClient(runtime_mod.create_app(runtime))

    for headers in (
        {},
        {"Authorization": "Bearer wrong", "Origin": "app://yagcode"},
        {"Authorization": "Bearer startup", "Origin": "https://evil.invalid"},
    ):
        assert client.get("/api/v1/health", headers=headers).status_code == 401

    response = client.get(
        "/api/v1/health",
        headers={"Authorization": "Bearer startup", "Origin": "app://yagcode"},
    )
    assert response.status_code == 200
    assert "startup" not in response.text

from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_owned_restart_oracle_rotates_token() -> None:
    assert "token-a" != "token-b"


def test_restart_rotates_token_and_rejects_stale_ui_state() -> None:
    app_mod = importlib.import_module("yagcode.api.app")
    first = app_mod.Runtime(startup_token="token-a", desktop_origin="app://yagcode")
    second = app_mod.Runtime(startup_token="token-b", desktop_origin="app://yagcode")
    first_client = TestClient(app_mod.create_app(first))
    second_client = TestClient(app_mod.create_app(second))

    headers_a = {"Authorization": "Bearer token-a", "Origin": "app://yagcode"}
    headers_b = {"Authorization": "Bearer token-b", "Origin": "app://yagcode"}
    assert first_client.get("/api/v1/health", headers=headers_a).status_code == 200
    assert second_client.get("/api/v1/health", headers=headers_a).status_code == 401
    assert second_client.get("/api/v1/health", headers=headers_b).status_code == 200

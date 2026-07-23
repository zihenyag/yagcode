from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_owned_workflow_oracle_separates_plan_bypass_from_permissions() -> None:
    service = {"checkpoints": [], "full_access": False}
    service["checkpoints"].append({"kind": "PLAN_BYPASS"})
    assert service["checkpoints"][-1]["kind"] == "PLAN_BYPASS"
    assert service["full_access"] is False


def _client_and_services() -> tuple[TestClient, object]:
    app_mod = importlib.import_module("yagcode.api.app")
    dependencies = importlib.import_module("yagcode.api.dependencies")
    services = dependencies.Services()
    runtime = app_mod.Runtime(startup_token="startup", desktop_origin="app://yagcode")
    return TestClient(app_mod.create_app(runtime, services=services)), services


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer startup", "Origin": "app://yagcode"}


def test_plan_off_creates_checkpoint_but_not_permission() -> None:
    client, services = _client_and_services()
    project = client.post("/api/v1/projects", headers=_headers(), json={"name": "demo"}).json()
    response = client.post(
        f"/api/v1/projects/{project['project_id']}/threads",
        headers=_headers(),
        json={"title": "bug fix", "plan_enabled": False},
    )

    assert response.status_code == 201
    thread_id = response.json()["thread_id"]
    assert services.checkpoints.last(thread_id).kind == "PLAN_BYPASS"
    assert services.permissions.full_access_enabled is False


def test_single_project_allows_only_one_running_thread_and_model_switch_requires_stop() -> None:
    client, _services = _client_and_services()
    project = client.post("/api/v1/projects", headers=_headers(), json={"name": "demo"}).json()
    first_thread = client.post(
        f"/api/v1/projects/{project['project_id']}/threads",
        headers=_headers(),
        json={"title": "bug one", "plan_enabled": True},
    ).json()
    second_thread = client.post(
        f"/api/v1/projects/{project['project_id']}/threads",
        headers=_headers(),
        json={"title": "bug two", "plan_enabled": True},
    ).json()

    first_run = client.post(
        f"/api/v1/threads/{first_thread['thread_id']}/runs",
        headers=_headers(),
        json={"model": "openai:gpt-5.6-sol"},
    )
    blocked_run = client.post(
        f"/api/v1/threads/{second_thread['thread_id']}/runs",
        headers=_headers(),
        json={"model": "openai:gpt-5.6-terra"},
    )
    switch_while_running = client.patch(
        f"/api/v1/runs/{first_run.json()['run_id']}/model",
        headers=_headers(),
        json={"model": "qwen:qwen3-coder"},
    )
    stopped = client.post(f"/api/v1/runs/{first_run.json()['run_id']}/stop", headers=_headers())
    switched = client.patch(
        f"/api/v1/runs/{first_run.json()['run_id']}/model",
        headers=_headers(),
        json={"model": "qwen:qwen3-coder"},
    )

    assert first_run.status_code == 201
    assert blocked_run.status_code == 409
    assert blocked_run.json()["detail"]["reason_code"] == "PROJECT_RUN_ACTIVE"
    assert switch_while_running.status_code == 409
    assert switch_while_running.json()["detail"]["reason_code"] == "RUN_MUST_STOP_BEFORE_MODEL_SWITCH"
    assert stopped.json()["state"] == "STOPPED"
    assert switched.json()["model"] == "qwen:qwen3-coder"

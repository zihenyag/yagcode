from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from yagcode.api.app import Runtime, create_app
from yagcode.api.dependencies import Services


def _client_and_services() -> tuple[TestClient, Services]:
    services = Services()
    runtime = Runtime(startup_token="startup", desktop_origin="app://yagcode")
    return TestClient(create_app(runtime, services=services)), services


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer startup", "Origin": "app://yagcode"}


def _start_run(client: TestClient) -> tuple[str, str]:
    project = client.post("/api/v1/projects", headers=_headers(), json={"name": "demo"}).json()
    thread = client.post(
        f"/api/v1/projects/{project['project_id']}/threads",
        headers=_headers(),
        json={"title": "bug fix", "plan_enabled": True},
    ).json()
    run = client.post(
        f"/api/v1/threads/{thread['thread_id']}/runs",
        headers=_headers(),
        json={"model": "openai:gpt-5.6-sol"},
    ).json()
    return thread["thread_id"], run["run_id"]


@pytest.mark.parametrize(
    "blocking_state",
    ["RUNNING", "WAITING_PERMISSION", "WAITING_PRIVACY", "COMPACTING", "STOPPING", "INTERRUPTED"],
)
def test_desktop_blocking_runs_include_all_non_closable_states(blocking_state: str) -> None:
    client, services = _client_and_services()
    thread_id, run_id = _start_run(client)
    services._runs[run_id].state = blocking_state

    response = client.get("/api/v1/desktop/blocking-runs", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {"runs": [{"id": run_id, "state": blocking_state, "title": thread_id}]}


def test_desktop_blocking_runs_exclude_stopped_runs() -> None:
    client, _services = _client_and_services()
    _thread_id, run_id = _start_run(client)
    client.post(f"/api/v1/runs/{run_id}/stop", headers=_headers())

    response = client.get("/api/v1/desktop/blocking-runs", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {"runs": []}

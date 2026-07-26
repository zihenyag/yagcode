"""In-memory application services used by governed desktop API routes."""

from __future__ import annotations

import secrets

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from starlette.requests import Request

from yagcode.api.schemas import ProjectView, RunView


RunRecordState: TypeAlias = Literal[
    "RUNNING",
    "WAITING_PERMISSION",
    "WAITING_PRIVACY",
    "COMPACTING",
    "STOPPING",
    "INTERRUPTED",
    "STOPPED",
]


class ApiDomainError(RuntimeError):
    def __init__(self, reason_code: str, *, http_status: int = 409) -> None:
        self.reason_code = reason_code
        self.http_status = http_status
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class Checkpoint:
    thread_id: str
    kind: Literal["PLAN_REQUIRED", "PLAN_BYPASS"]


@dataclass(slots=True)
class CheckpointStore:
    _records: list[Checkpoint] = field(default_factory=list)

    def append(self, checkpoint: Checkpoint) -> None:
        self._records.append(checkpoint)

    def last(self, thread_id: str) -> Checkpoint:
        for checkpoint in reversed(self._records):
            if checkpoint.thread_id == thread_id:
                return checkpoint
        raise ApiDomainError("CHECKPOINT_NOT_FOUND", http_status=404)


@dataclass(slots=True)
class PermissionState:
    full_access_enabled: bool = False


@dataclass(frozen=True, slots=True)
class ThreadRecord:
    thread_id: str
    project_id: str
    title: str
    plan_enabled: bool
    state: Literal["READY", "RUNNING", "STOPPED"] = "READY"


@dataclass(slots=True)
class RunRecord:
    run_id: str
    project_id: str
    thread_id: str
    model: str
    generation: int
    state: RunRecordState


@dataclass(frozen=True, slots=True)
class IntentChallenge:
    intent_id: str
    intent_type: str
    one_time_token: str
    resource_id: str


@dataclass(frozen=True, slots=True)
class PrivilegedActionResult:
    intent_id: str
    intent_type: str
    state: Literal["EXECUTED"]


@dataclass(slots=True)
class IntentStore:
    _next_intent: int = 0
    _records: dict[str, IntentChallenge] = field(default_factory=dict)

    def create(self, intent_type: str, resource_id: str) -> IntentChallenge:
        self._next_intent += 1
        intent = IntentChallenge(
            intent_id=f"intent-{self._next_intent}",
            intent_type=intent_type,
            one_time_token=secrets.token_urlsafe(16),
            resource_id=resource_id,
        )
        self._records[intent.intent_id] = intent
        return intent

    def consume(self, intent_id: str, one_time_token: str) -> PrivilegedActionResult:
        intent = self._records.get(intent_id)
        if intent is None:
            raise ApiDomainError("INTENT_NOT_FOUND", http_status=404)
        if not secrets.compare_digest(intent.one_time_token, one_time_token):
            raise ApiDomainError("INTENT_TOKEN_INVALID", http_status=403)
        del self._records[intent_id]
        return PrivilegedActionResult(intent.intent_id, intent.intent_type, "EXECUTED")


class Services:
    def __init__(self, profile_id: str = "default") -> None:
        self.profile_id = profile_id
        self.checkpoints = CheckpointStore()
        self.permissions = PermissionState()
        self.intents = IntentStore()
        self._next_project = 0
        self._next_thread = 0
        self._next_run = 0
        self._projects: dict[str, ProjectView] = {}
        self._threads: dict[str, ThreadRecord] = {}
        self._runs: dict[str, RunRecord] = {}
        self._active_run_by_project: dict[str, str] = {}

    def create_project(self, name: str) -> ProjectView:
        self._next_project += 1
        project = ProjectView(kind="project", project_id=f"project-{self._next_project}", name=name)
        self._projects[project.project_id] = project
        return project

    def create_thread(self, project_id: str, *, title: str, plan_enabled: bool) -> ThreadRecord:
        if project_id not in self._projects:
            raise ApiDomainError("PROJECT_NOT_FOUND", http_status=404)
        self._next_thread += 1
        thread = ThreadRecord(f"thread-{self._next_thread}", project_id, title, plan_enabled)
        self._threads[thread.thread_id] = thread
        self.checkpoints.append(
            Checkpoint(thread.thread_id, "PLAN_REQUIRED" if plan_enabled else "PLAN_BYPASS")
        )
        return thread

    def start_run(self, thread_id: str, *, model: str) -> RunView:
        thread = self._threads.get(thread_id)
        if thread is None:
            raise ApiDomainError("THREAD_NOT_FOUND", http_status=404)
        if thread.project_id in self._active_run_by_project:
            raise ApiDomainError("PROJECT_RUN_ACTIVE")
        self._next_run += 1
        run = RunRecord(f"run-{self._next_run}", thread.project_id, thread.thread_id, model, 0, "RUNNING")
        self._runs[run.run_id] = run
        self._active_run_by_project[thread.project_id] = run.run_id
        return RunView(kind="run", run_id=run.run_id, state=run.state, generation=run.generation)

    def stop_run(self, run_id: str) -> RunRecord:
        run = self._runs.get(run_id)
        if run is None:
            raise ApiDomainError("RUN_NOT_FOUND", http_status=404)
        run.state = "STOPPED"
        self._active_run_by_project.pop(run.project_id, None)
        return run

    def switch_model(self, run_id: str, *, model: str) -> RunRecord:
        run = self._runs.get(run_id)
        if run is None:
            raise ApiDomainError("RUN_NOT_FOUND", http_status=404)
        if run.state != "STOPPED":
            raise ApiDomainError("RUN_MUST_STOP_BEFORE_MODEL_SWITCH")
        run.model = model
        run.generation += 1
        return run

    def blocking_runs(self) -> tuple[RunRecord, ...]:
        blocking_states = {
            "RUNNING",
            "WAITING_PERMISSION",
            "WAITING_PRIVACY",
            "COMPACTING",
            "STOPPING",
            "INTERRUPTED",
        }
        return tuple(
            run for run in self._runs.values() if run.state in blocking_states
        )


def get_services(request: Request) -> Services:
    services = getattr(request.app.state, "services", None)
    if not isinstance(services, Services):
        raise ApiDomainError("SERVICES_UNAVAILABLE", http_status=500)
    return services


__all__ = [
    "ApiDomainError",
    "Checkpoint",
    "CheckpointStore",
    "IntentChallenge",
    "PermissionState",
    "PrivilegedActionResult",
    "RunRecord",
    "RunRecordState",
    "Services",
    "ThreadRecord",
    "get_services",
]

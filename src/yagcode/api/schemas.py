"""Public API view and event schemas with snake_case wire names."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


STRICT_MODEL = ConfigDict(extra="forbid", strict=True)


class ReviewView(BaseModel):
    model_config = STRICT_MODEL
    kind: Literal["review"]
    review_id: str
    state: Literal[
        "NOT_READY",
        "INCOMPLETE",
        "READY",
        "ACCEPTING",
        "ACCEPTED",
        "REJECTED",
        "CONFLICT",
        "RECOVERY_REQUIRED",
    ]
    generation: int = Field(ge=0)
    summary: str


class RunView(BaseModel):
    model_config = STRICT_MODEL
    kind: Literal["run"]
    run_id: str
    state: str
    generation: int = Field(ge=0)


class TaskView(BaseModel):
    model_config = STRICT_MODEL
    kind: Literal["task"]
    task_id: str
    state: str


class ProjectView(BaseModel):
    model_config = STRICT_MODEL
    kind: Literal["project"]
    project_id: str
    name: str


PublicView = Annotated[ReviewView | RunView | TaskView | ProjectView, Field(discriminator="kind")]


class RunStatePayload(BaseModel):
    model_config = STRICT_MODEL
    run_id: str
    state: str


class ActionIntentPayload(BaseModel):
    model_config = STRICT_MODEL
    kind: str


EventPayload = RunStatePayload | ActionIntentPayload


class EventEnvelope(BaseModel):
    model_config = STRICT_MODEL
    profile_id: str
    sequence: int = Field(ge=1)
    event_type: Literal["run.state", "action.intent"]
    generation: int | None = Field(default=None, ge=0)
    payload: EventPayload


PUBLIC_VIEW_ADAPTER: TypeAdapter[ReviewView | RunView | TaskView | ProjectView] = TypeAdapter(PublicView)
EVENT_ADAPTER: TypeAdapter[EventEnvelope] = TypeAdapter(EventEnvelope)


def review_fixture() -> ReviewView:
    return ReviewView(
        kind="review",
        review_id="review-1",
        state="READY",
        generation=1,
        summary="2 files changed",
    )


def event_fixture() -> EventEnvelope:
    return EventEnvelope(
        profile_id="profile-1",
        sequence=1,
        event_type="run.state",
        generation=1,
        payload=RunStatePayload(run_id="run-1", state="RUNNING"),
    )


__all__ = [
    "EVENT_ADAPTER",
    "ActionIntentPayload",
    "EventPayload",
    "PUBLIC_VIEW_ADAPTER",
    "EventEnvelope",
    "ProjectView",
    "PublicView",
    "ReviewView",
    "RunStatePayload",
    "RunView",
    "TaskView",
    "event_fixture",
    "review_fixture",
]

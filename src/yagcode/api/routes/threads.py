from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from yagcode.api.dependencies import ApiDomainError, Services, get_services
from yagcode.api.routes._errors import raise_http


router = APIRouter()


class CreateThreadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str
    plan_enabled: bool = True


class ThreadView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    thread_id: str
    project_id: str
    title: str
    plan_enabled: bool
    state: Literal["READY", "RUNNING", "STOPPED"]


@router.post("/projects/{project_id}/threads", response_model=ThreadView, status_code=201)
def create_thread(
    project_id: str,
    request: CreateThreadRequest,
    services: Services = Depends(get_services),
) -> ThreadView:
    try:
        thread = services.create_thread(project_id, title=request.title, plan_enabled=request.plan_enabled)
    except ApiDomainError as error:
        raise_http(error)
    return ThreadView(
        thread_id=thread.thread_id,
        project_id=thread.project_id,
        title=thread.title,
        plan_enabled=thread.plan_enabled,
        state=thread.state,
    )


__all__ = ["router"]

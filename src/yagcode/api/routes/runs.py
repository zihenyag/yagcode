from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from yagcode.api.dependencies import ApiDomainError, RunRecordState, Services, get_services
from yagcode.api.routes._errors import raise_http
from yagcode.api.schemas import RunView


router = APIRouter()


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1)


class SwitchModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1)


class RunDetailView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: str
    state: RunRecordState
    model: str
    generation: int


@router.post("/threads/{thread_id}/runs", response_model=RunView, status_code=201)
def start_run(
    thread_id: str,
    request: StartRunRequest,
    services: Services = Depends(get_services),
) -> RunView:
    try:
        return services.start_run(thread_id, model=request.model)
    except ApiDomainError as error:
        raise_http(error)


@router.post("/runs/{run_id}/stop", response_model=RunDetailView)
def stop_run(run_id: str, services: Services = Depends(get_services)) -> RunDetailView:
    try:
        run = services.stop_run(run_id)
    except ApiDomainError as error:
        raise_http(error)
    return RunDetailView(run_id=run.run_id, state=run.state, model=run.model, generation=run.generation)


@router.patch("/runs/{run_id}/model", response_model=RunDetailView)
def switch_model(
    run_id: str,
    request: SwitchModelRequest,
    services: Services = Depends(get_services),
) -> RunDetailView:
    try:
        run = services.switch_model(run_id, model=request.model)
    except ApiDomainError as error:
        raise_http(error)
    return RunDetailView(run_id=run.run_id, state=run.state, model=run.model, generation=run.generation)


__all__ = ["router"]

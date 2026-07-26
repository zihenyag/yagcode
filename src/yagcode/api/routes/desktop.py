from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from yagcode.api.dependencies import Services, get_services


router = APIRouter()

BlockingRunState = Literal[
    "RUNNING",
    "WAITING_PERMISSION",
    "WAITING_PRIVACY",
    "COMPACTING",
    "STOPPING",
    "INTERRUPTED",
]


class BlockingRunView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    state: BlockingRunState
    title: str


class BlockingRunsView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    runs: tuple[BlockingRunView, ...]


@router.get("/desktop/blocking-runs", response_model=BlockingRunsView)
def blocking_runs(services: Services = Depends(get_services)) -> BlockingRunsView:
    return BlockingRunsView(
        runs=tuple(
            BlockingRunView(id=run.run_id, state=run.state, title=run.thread_id)
            for run in services.blocking_runs()
        )
    )


__all__ = ["router"]

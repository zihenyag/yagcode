from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from yagcode.api.dependencies import Services, get_services
from yagcode.api.schemas import ProjectView


router = APIRouter()


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str


@router.post("/projects", response_model=ProjectView, status_code=201)
def create_project(request: CreateProjectRequest, services: Services = Depends(get_services)) -> ProjectView:
    return services.create_project(request.name)


__all__ = ["router"]

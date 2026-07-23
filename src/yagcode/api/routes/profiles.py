from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from yagcode.api.dependencies import Services, get_services


router = APIRouter()


class ProfileView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    profile_id: str


@router.get("/profiles/current", response_model=ProfileView)
def current_profile(services: Services = Depends(get_services)) -> ProfileView:
    return ProfileView(profile_id=services.profile_id)


__all__ = ["router"]

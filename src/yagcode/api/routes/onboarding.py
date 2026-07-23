from __future__ import annotations

from fastapi import APIRouter

from yagcode.onboarding.git_preflight import GitOnboardingPlan, GitPreflightService


router = APIRouter()


@router.get("/onboarding/git/preflight", response_model=GitOnboardingPlan)
def git_preflight(platform: str, arch: str, has_git: bool = False, is_git_repository: bool = False) -> GitOnboardingPlan:
    return GitPreflightService().plan(
        has_git=has_git,
        is_git_repository=is_git_repository,
        platform=platform,
        arch=arch,
    )


__all__ = ["router"]

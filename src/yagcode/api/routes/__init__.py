"""Governed sidecar API route registry."""

from __future__ import annotations

from fastapi import APIRouter

from yagcode.api.routes import credentials, intents, memory, onboarding, profiles, projects, review, runs, threads


def routers() -> tuple[APIRouter, ...]:
    return (
        profiles.router,
        projects.router,
        threads.router,
        runs.router,
        review.router,
        memory.router,
        credentials.router,
        onboarding.router,
        intents.router,
    )


__all__ = ["routers"]

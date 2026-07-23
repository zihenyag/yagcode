"""FastAPI application factory for the local sidecar."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI

from yagcode.api.auth import AuthConfig, SidecarAuthMiddleware, digest_token
from yagcode.api.health import router as health_router


@dataclass(frozen=True, slots=True)
class Runtime:
    startup_token: str
    desktop_origin: str

    @property
    def startup_token_digest(self) -> str:
        return digest_token(self.startup_token)


def create_app(runtime: Runtime) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        SidecarAuthMiddleware,
        config=AuthConfig(
            token_digest=runtime.startup_token_digest,
            allowed_origin=runtime.desktop_origin,
        ),
    )
    app.include_router(health_router, prefix="/api/v1")
    return app


__all__ = ["Runtime", "create_app"]

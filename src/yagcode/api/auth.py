"""Loopback sidecar bearer/origin authentication."""

from __future__ import annotations

import hashlib
import hmac

from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AuthConfig:
    token_digest: str
    allowed_origin: str


class SidecarAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, config: AuthConfig) -> None:
        super().__init__(app)
        self._config = config

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        origin = request.headers.get("origin")
        cors_headers = {
            "Access-Control-Allow-Origin": self._config.allowed_origin,
            "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
            "Access-Control-Allow-Headers": "authorization,content-type,x-yagcode-principal",
        }
        if request.method == "OPTIONS":
            if origin != self._config.allowed_origin:
                return JSONResponse({"detail": {"reason_code": "SIDECAR_AUTH_REQUIRED"}}, status_code=401)
            return Response(status_code=204, headers=cors_headers)
        authorization = request.headers.get("authorization", "")
        prefix = "Bearer "
        token = authorization.removeprefix(prefix) if authorization.startswith(prefix) else ""
        if origin != self._config.allowed_origin or not hmac.compare_digest(
            digest_token(token), self._config.token_digest
        ):
            return JSONResponse({"detail": {"reason_code": "SIDECAR_AUTH_REQUIRED"}}, status_code=401)
        response = await call_next(request)
        for key, value in cors_headers.items():
            response.headers[key] = value
        return response


__all__ = ["AuthConfig", "SidecarAuthMiddleware", "digest_token"]

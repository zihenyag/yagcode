"""Health endpoint for the authenticated loopback API."""

from __future__ import annotations

from fastapi import APIRouter


router = APIRouter()


@router.get("/health")
def health() -> dict[str, object]:
    return {"version": "0.1.0", "status": "ok", "capabilities": {"sse": True}}


__all__ = ["router"]

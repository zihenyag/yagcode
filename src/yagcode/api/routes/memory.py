from __future__ import annotations

from fastapi import APIRouter


router = APIRouter()


@router.get("/memory/inbox")
def memory_inbox() -> dict[str, object]:
    return {"items": []}


__all__ = ["router"]

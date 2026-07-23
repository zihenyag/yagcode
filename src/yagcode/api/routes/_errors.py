"""Shared API route helpers."""

from __future__ import annotations

from typing import NoReturn

from fastapi import Header, HTTPException

from yagcode.api.dependencies import ApiDomainError


def raise_http(error: ApiDomainError) -> NoReturn:
    raise HTTPException(
        status_code=error.http_status,
        detail={"reason_code": error.reason_code},
    ) from None


def require_main_principal(x_yagcode_principal: str | None = Header(default=None)) -> None:
    if x_yagcode_principal != "main":
        raise HTTPException(status_code=403, detail={"reason_code": "MAIN_PRINCIPAL_REQUIRED"})


__all__ = ["raise_http", "require_main_principal"]

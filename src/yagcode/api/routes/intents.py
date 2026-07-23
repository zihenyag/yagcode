from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from yagcode.api.dependencies import ApiDomainError, PrivilegedActionResult, Services, get_services
from yagcode.api.routes._errors import raise_http, require_main_principal


router = APIRouter()


class ConsumeIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    one_time_token: str


@router.post("/intents/{intent_id}/consume", response_model=PrivilegedActionResult)
def consume_intent(
    intent_id: str,
    request: ConsumeIntentRequest,
    _: None = Depends(require_main_principal),
    services: Services = Depends(get_services),
) -> PrivilegedActionResult:
    try:
        return services.intents.consume(intent_id, request.one_time_token)
    except ApiDomainError as error:
        raise_http(error)


__all__ = ["router"]

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from yagcode.api.dependencies import IntentChallenge, PrivilegedActionResult, Services, get_services
from yagcode.api.routes._errors import require_main_principal


router = APIRouter()


class CredentialStatusView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: str
    configured: bool


@router.get("/credentials/{provider}", response_model=CredentialStatusView)
def credential_status(provider: str) -> CredentialStatusView:
    return CredentialStatusView(provider=provider, configured=False)


@router.delete("/credentials/{provider}", response_model=PrivilegedActionResult)
def clear_credential(
    provider: str,
    _: None = Depends(require_main_principal),
    services: Services = Depends(get_services),
) -> PrivilegedActionResult:
    challenge = services.intents.create("CLEAR_CREDENTIAL", provider)
    return services.intents.consume(challenge.intent_id, challenge.one_time_token)


@router.post("/credentials/{provider}/clear-intent", response_model=IntentChallenge, status_code=201)
def clear_credential_intent(provider: str, services: Services = Depends(get_services)) -> IntentChallenge:
    return services.intents.create("CLEAR_CREDENTIAL", provider)


__all__ = ["router"]

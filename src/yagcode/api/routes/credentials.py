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
    status: str
    updated_at: str | None
    detail: str
    docs_url: str


@router.get("/credentials/{provider}", response_model=CredentialStatusView)
def credential_status(provider: str, services: Services = Depends(get_services)) -> CredentialStatusView:
    binding = services.desktop_demo.configured_providers.get(provider)
    endpoint = services._provider_endpoints.get(provider)
    return CredentialStatusView(
        provider=provider,
        configured=binding is not None and binding.status == "verified",
        status=binding.status if binding is not None else "missing",
        updated_at=binding.updated_at if binding is not None else None,
        detail=binding.detail if binding is not None else "尚未绑定",
        docs_url=endpoint.docs_url if endpoint is not None else "",
    )


@router.delete("/credentials/{provider}", response_model=PrivilegedActionResult)
def clear_credential(
    provider: str,
    _: None = Depends(require_main_principal),
    services: Services = Depends(get_services),
) -> PrivilegedActionResult:
    challenge = services.intents.create("CLEAR_CREDENTIAL", provider)
    result = services.intents.consume(challenge.intent_id, challenge.one_time_token)
    services.delete_demo_provider(provider)
    return result


@router.post("/credentials/{provider}/clear-intent", response_model=IntentChallenge, status_code=201)
def clear_credential_intent(provider: str, services: Services = Depends(get_services)) -> IntentChallenge:
    return services.intents.create("CLEAR_CREDENTIAL", provider)


__all__ = ["router"]

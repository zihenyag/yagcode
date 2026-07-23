from __future__ import annotations

from fastapi import APIRouter, Depends

from yagcode.api.dependencies import IntentChallenge, PrivilegedActionResult, Services, get_services
from yagcode.api.routes._errors import require_main_principal


router = APIRouter()


@router.post("/review/{review_id}/accept", response_model=PrivilegedActionResult)
def accept_review(
    review_id: str,
    _: None = Depends(require_main_principal),
    services: Services = Depends(get_services),
) -> PrivilegedActionResult:
    challenge = services.intents.create("ACCEPT_REVIEW", review_id)
    return services.intents.consume(challenge.intent_id, challenge.one_time_token)


@router.post("/review/{review_id}/accept-intent", response_model=IntentChallenge, status_code=201)
def accept_review_intent(review_id: str, services: Services = Depends(get_services)) -> IntentChallenge:
    return services.intents.create("ACCEPT_REVIEW", review_id)


__all__ = ["router"]

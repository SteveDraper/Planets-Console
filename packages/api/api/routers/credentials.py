"""Account credential routes: probe, exchange, drop."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from api.planets_nu import PlanetsNuClient
from api.services.credential_service import CredentialService
from api.services.deps import get_credential_service
from api.transport.credentials import (
    CredentialExchangeRequest,
    CredentialExchangeResponse,
    CredentialProbeResponse,
)

router = APIRouter(prefix="/v1/credentials", tags=["credentials"])


def get_planets_client() -> PlanetsNuClient:
    return PlanetsNuClient.from_config()


@router.get("/probe", response_model=CredentialProbeResponse)
def probe_credentials(
    username: Annotated[str, Query(min_length=1)],
    svc: CredentialService = Depends(get_credential_service),
) -> CredentialProbeResponse:
    """Return whether a decryptable account API key exists (no Planets.nu call)."""
    return CredentialProbeResponse(present=svc.probe(username))


@router.post("/exchange", response_model=CredentialExchangeResponse)
def exchange_credentials(
    body: CredentialExchangeRequest,
    svc: CredentialService = Depends(get_credential_service),
    planets: PlanetsNuClient = Depends(get_planets_client),
) -> CredentialExchangeResponse:
    """Login exchange: always call Planets.nu and store an obfuscated account API key."""
    svc.exchange(body.username, body.password, planets)
    return CredentialExchangeResponse(ok=True)


@router.delete("/{username}", status_code=204)
def drop_credentials(
    username: str,
    svc: CredentialService = Depends(get_credential_service),
) -> Response:
    """Account API key drop for ``username``."""
    svc.drop(username)
    return Response(status_code=204)

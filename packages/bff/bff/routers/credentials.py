"""SPA credential routes: probe, login exchange, account API key drop."""

from typing import Annotated

from api.transport.credentials import (
    CredentialExchangeRequest,
    CredentialExchangeResponse,
    CredentialProbeResponse,
)
from fastapi import APIRouter, Depends, Query, Response

from bff.core_client import CoreClient, get_core_client

router = APIRouter()

CoreClientDep = Annotated[CoreClient, Depends(get_core_client)]


@router.get("/probe", response_model=CredentialProbeResponse)
def probe_credentials(
    username: Annotated[str, Query(min_length=1)],
    core: CoreClientDep,
) -> CredentialProbeResponse:
    """Credential probe: decryptable account API key present? (no Planets.nu call)."""
    return CredentialProbeResponse(present=core.probe_credentials(username))


@router.post("/exchange", response_model=CredentialExchangeResponse)
def exchange_credentials(
    body: CredentialExchangeRequest,
    core: CoreClientDep,
) -> CredentialExchangeResponse:
    """Login exchange: Planets.nu login + store obfuscated account API key."""
    core.exchange_credentials(body.username, body.password)
    return CredentialExchangeResponse(ok=True)


@router.delete("/{username}", status_code=204)
def drop_credentials(
    username: str,
    core: CoreClientDep,
) -> Response:
    """Account API key drop for the given login name."""
    core.drop_credentials(username)
    return Response(status_code=204)

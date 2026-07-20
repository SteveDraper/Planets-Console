"""HTTP transport models for credential probe / exchange / drop."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CredentialExchangeRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class CredentialProbeResponse(BaseModel):
    present: bool


class CredentialExchangeResponse(BaseModel):
    ok: bool = True

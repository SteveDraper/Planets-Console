"""BFF OpenAPI models for fleet table NDJSON stream events."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class FleetTableStreamLedgerUpdatedEvent(BaseModel):
    type: Literal["ledger_updated"]
    playerId: int | None = None
    ledger: dict[str, Any]


class FleetTableStreamRecordRefinedEvent(BaseModel):
    type: Literal["record_refined"]
    playerId: int | None = None
    record: dict[str, Any]


class FleetTableStreamProvenanceEvent(BaseModel):
    type: Literal["provenance"]
    playerId: int | None = None
    turnEvidenceAtN: bool
    priorLedgerAtNMinus1: bool
    isFinal: bool


class FleetTableStreamCompleteEvent(BaseModel):
    type: Literal["complete"]
    playerId: int | None = None
    isFinal: bool
    summary: str


class FleetTableStreamErrorEvent(BaseModel):
    type: Literal["error"]
    playerId: int | None = None
    detail: str


__all__ = [
    "FleetTableStreamCompleteEvent",
    "FleetTableStreamErrorEvent",
    "FleetTableStreamLedgerUpdatedEvent",
    "FleetTableStreamProvenanceEvent",
    "FleetTableStreamRecordRefinedEvent",
]

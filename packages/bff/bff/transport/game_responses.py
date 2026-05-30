"""BFF response models for game and turn payloads."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from typing import Any, get_type_hints

from api.models.game import GameInfo, TurnInfo
from pydantic import BaseModel, ConfigDict, Field, create_model, model_serializer


class OmitNullDiagnosticsBase(BaseModel):
    """Optional BFF request diagnostics; omitted from JSON when null."""

    diagnostics: dict[str, Any] | None = Field(
        default=None,
        description="Request timing tree; present when includeDiagnostics=true.",
    )

    @model_serializer(mode="wrap")
    def _omit_diagnostics_when_none(self, handler: Callable[[BaseModel], Any]) -> Any:
        data = handler(self)
        if isinstance(data, dict) and data.get("diagnostics") is None:
            out = dict(data)
            out.pop("diagnostics", None)
            return out
        return data


def bff_dataclass_response_with_diagnostics(
    pydantic_model_name: str,
    dataclass_type: type,
) -> type[BaseModel]:
    """Pydantic model mirroring ``dataclass_type`` with optional BFF ``diagnostics`` (OpenAPI)."""
    hints = get_type_hints(dataclass_type, include_extras=True)
    field_defs: dict = {f.name: (hints[f.name], Field()) for f in fields(dataclass_type)}

    return create_model(
        pydantic_model_name,
        __base__=OmitNullDiagnosticsBase,
        __config__=ConfigDict(),
        __module__=__name__,
        **field_defs,
    )


BffGameInfoResponse = bff_dataclass_response_with_diagnostics("BffGameInfoResponse", GameInfo)
BffTurnInfoResponse = bff_dataclass_response_with_diagnostics("BffTurnInfoResponse", TurnInfo)


class StoredTurnPerspectivesResponse(OmitNullDiagnosticsBase):
    """1-based perspective slots that already have turn data in storage."""

    perspectives: list[int] = Field(default_factory=list)


class StellarCartographyTurnSummaryResponse(OmitNullDiagnosticsBase):
    """Lightweight turn facts for Stellar Cartography sidebar state."""

    ionStormCount: int
    nuIonStorms: bool

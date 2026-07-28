"""BFF transport models for homeworld layout-prior solver telemetry (#274)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LayoutPriorDiagnosticsShellContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    game_id: int = Field(alias="gameId")
    perspective: int
    turn: int = Field(ge=1)


class LayoutPriorReportsResponse(BaseModel):
    """Newest-first layout-prior solver run reports for one shell context."""

    model_config = ConfigDict(populate_by_name=True)

    shell: LayoutPriorDiagnosticsShellContext
    reports: list[dict[str, Any]]

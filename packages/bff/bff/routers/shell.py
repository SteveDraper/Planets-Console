"""SPA shell bootstrap: config surfaced for first paint without hard-coding in the frontend."""

from collections.abc import Callable
from typing import Any

from api.services.compute_diagnostics_service import compute_diagnostics_enabled
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_serializer

from bff.config import get_config
from bff.diagnostics_dep import (
    IncludeDiagnostics,
    finish_response,
    optional_request_root,
    with_timed_child,
)

router = APIRouter()


class ShellBootstrapResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    show_initial_game: str | None = Field(
        default=None,
        serialization_alias="showInitialGame",
        description="Stored game id to load automatically without login, or null when disabled.",
    )
    compute_diagnostics_enabled: bool = Field(
        default=False,
        serialization_alias="computeDiagnosticsEnabled",
        description="When true, the diagnostics modal exposes compute orchestrator controls.",
    )
    fleet_location_ring_strength_scale: int = Field(
        default=10_000,
        serialization_alias="fleetLocationRingStrengthScale",
        description=(
            "Absolute host-mil-points scale for fleet location ring opacity and annulus fill "
            "(from bff.fleet.location_ring_strength_scale)."
        ),
        ge=1,
    )
    diagnostics: dict[str, Any] | None = Field(
        default=None,
        description="Request timing tree; present when includeDiagnostics=true.",
    )

    @model_serializer(mode="wrap")
    def _json_omit_diagnostics_when_none(self, handler: Callable[[BaseModel], Any]) -> Any:
        data = handler(self)
        if isinstance(data, dict) and data.get("diagnostics") is None:
            out = dict(data)
            out.pop("diagnostics", None)
            return out
        return data


@router.get("/bootstrap", response_model=ShellBootstrapResponse)
def get_shell_bootstrap(include: IncludeDiagnostics = False) -> object:
    """Return shell-oriented server config for the SPA (e.g. optional default game id)."""
    raw = get_config().show_initial_game
    if raw is None:
        show: str | None = None
    else:
        trimmed = raw.strip()
        show = trimmed if trimmed else None
    root = optional_request_root(include, "GET", "/shell/bootstrap", handler="get_shell_bootstrap")

    def work() -> ShellBootstrapResponse:
        return ShellBootstrapResponse(
            show_initial_game=show,
            compute_diagnostics_enabled=compute_diagnostics_enabled(),
            fleet_location_ring_strength_scale=get_config().fleet.location_ring_strength_scale,
        )

    result = with_timed_child(root, "get_shell_bootstrap", "total", work)
    return finish_response(result, root)

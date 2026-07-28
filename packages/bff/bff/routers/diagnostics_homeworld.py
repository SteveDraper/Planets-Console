"""Homeworld layout-prior solver telemetry BFF routes (#274).

Thin reshape over Core ``layout_prior_diagnostics_service``. Distinct from
compute-diagnostics routes -- do not mix homeworld fields into those APIs.
"""

from __future__ import annotations

from api.services import layout_prior_diagnostics_service as layout_prior_diagnostics
from fastapi import APIRouter, Query

from bff.transport.layout_prior_diagnostics_responses import LayoutPriorReportsResponse

router = APIRouter()


@router.get(
    "/homeworld/layout-prior-reports",
    response_model=LayoutPriorReportsResponse,
)
def get_layout_prior_reports(
    game_id: int = Query(..., alias="gameId"),
    perspective: int = Query(..., ge=0),
    turn: int = Query(..., ge=1),
) -> LayoutPriorReportsResponse:
    """Return newest-first layout-prior solver run reports for one shell."""
    wire = layout_prior_diagnostics.get_layout_prior_reports_wire(
        game_id=game_id,
        perspective=perspective,
        turn=turn,
    )
    return LayoutPriorReportsResponse.model_validate(wire)

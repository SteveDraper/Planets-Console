"""Map/table compute handler for the homeworld locator analytic."""

from __future__ import annotations

from api.analytics.compute_context import AnalyticComputeContext, invoke_analytic_compute
from api.analytics.homeworld_locator.baseline_ensure import materialize_homeworld_candidate_view
from api.analytics.homeworld_locator.compute_services import resolve_homeworld_services
from api.analytics.homeworld_locator.constants import ANALYTIC_ID
from api.analytics.homeworld_locator.sector_overlays import (
    build_homeworld_sector_overlays_for_turn,
)
from api.analytics.homeworld_locator.serialization import homeworld_candidate_record_to_json
from api.analytics.homeworld_locator.types import HomeworldCandidateView
from api.analytics.options import TurnAnalyticsOptions
from api.concepts.homeworld_layout import homeworld_locator_inactive_reason
from api.concepts.map_region_coverage import map_region_overlay_to_wire
from api.models.game import TurnInfo


def _view_to_wire(
    view: HomeworldCandidateView,
    *,
    region_overlays: list[dict] | None = None,
) -> dict:
    markers = [
        {
            "planetId": row.planet_id,
            "perspective": row.perspective,
            "confidenceTier": row.confidence_tier,
            "attribution": row.attribution,
            "isMostProbable": row.is_most_probable,
        }
        for row in view.candidates
    ]
    rows = [
        {
            **homeworld_candidate_record_to_json(row),
            "isMostProbable": row.is_most_probable,
        }
        for row in view.candidates
    ]
    return {
        "analyticId": ANALYTIC_ID,
        "available": view.available,
        "inactiveReason": view.inactive_reason,
        "baselineDegraded": view.baseline_degraded,
        "baselineTurn": view.baseline_turn if view.baseline_turn > 0 else None,
        "markers": markers,
        "rows": rows,
        "regionOverlays": region_overlays if region_overlays is not None else [],
        "nodes": [],
        "edges": [],
    }


def compute_homeworld_locator(ctx: AnalyticComputeContext) -> dict:
    """Return candidate view for map markers, sector overlays, and tabular rows."""
    inactive = homeworld_locator_inactive_reason(ctx.turn.settings)
    if inactive is not None:
        return _view_to_wire(
            HomeworldCandidateView(
                candidates=(),
                baseline_turn=0,
                baseline_degraded=False,
                available=False,
                inactive_reason=inactive,
            )
        )

    services = resolve_homeworld_services(ctx.exports)
    view = materialize_homeworld_candidate_view(services, shell_turn=ctx.turn)
    overlays = build_homeworld_sector_overlays_for_turn(
        ctx.turn,
        view,
        shell_perspective=services.perspective,
        game_info=services.game_info,
        game_id=services.game_id,
    )
    return _view_to_wire(
        view,
        region_overlays=[map_region_overlay_to_wire(overlay) for overlay in overlays],
    )


def get_homeworld_locator(
    turn: TurnInfo,
    options: TurnAnalyticsOptions | None = None,
    *,
    export_services: dict[str, object] | None = None,
) -> dict:
    """Convenience entry for tests and direct callers."""
    return invoke_analytic_compute(
        compute_homeworld_locator,
        turn,
        options,
        export_services=export_services,
    )

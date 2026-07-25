"""Visibility analytic: map region overlays for sensor coverage."""

from __future__ import annotations

from api.analytics.catalog import catalog_entry
from api.analytics.compute_context import AnalyticComputeContext, invoke_analytic_compute
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.registration import TurnAnalyticRegistration
from api.concepts.map_region_coverage import map_region_overlay_to_wire
from api.concepts.visibility_coverage import build_visibility_overlays
from api.models.game import TurnInfo

ANALYTIC_ID = "visibility"


def compute_visibility_map(ctx: AnalyticComputeContext) -> dict:
    """Return hybrid ``regionOverlays`` for ship-scan and Sensor Sweep kinds."""
    overlays = build_visibility_overlays(ctx.turn)
    return {
        "analyticId": ANALYTIC_ID,
        "regionOverlays": [map_region_overlay_to_wire(overlay) for overlay in overlays],
        "nodes": [],
        "edges": [],
    }


def get_visibility_map(
    turn: TurnInfo,
    options: TurnAnalyticsOptions | None = None,
) -> dict:
    """Convenience entry for tests and direct callers."""
    return invoke_analytic_compute(compute_visibility_map, turn, options)


REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_visibility_map,
    export_catalog=empty_export_catalog_for(ANALYTIC_ID),
)

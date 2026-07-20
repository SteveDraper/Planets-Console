"""Temporary map-only demo analytic for hybrid map region overlays.

Produces shaded coverage via the shared Core hybrid coverage helper so the SPA
can merge and blit without the Visibility analytic. Remove this registration
when Visibility lands and consumes ``regionOverlays`` instead.
"""

from __future__ import annotations

from api.analytics.catalog import catalog_entry
from api.analytics.compute_context import AnalyticComputeContext, invoke_analytic_compute
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.registration import TurnAnalyticRegistration
from api.concepts.map_region_coverage import (
    CoverageOrigin,
    build_hybrid_coverage,
    hybrid_coverage_to_overlay,
    map_region_overlay_to_wire,
)
from api.models.game import TurnInfo

ANALYTIC_ID = "map-region-demo"

# Demo style defaults (Visibility will own client overrides later).
_DEMO_KIND = "demo"
_DEMO_OVERLAY_ID = "demo-coverage"
_DEMO_FILL_COLOR = "#22c55e"
_DEMO_FILL_OPACITY = 0.25
_DEMO_BASE_RANGE_LY = 150.0
_DEMO_MAX_ORIGINS = 2


def _demo_origins(turn: TurnInfo) -> list[CoverageOrigin]:
    """Pick owned planets plus a nebula-local origin when nebulas exist.

    Planet origins show compact disk-only coverage on empty maps. A origin at
    the first nebula center ensures nebula-local patches appear for demo blit.
    """
    viewpoint_id = turn.player.id
    owned = [p for p in turn.planets if p.ownerid == viewpoint_id]
    candidates = owned if owned else list(turn.planets)
    origins: list[CoverageOrigin] = []
    for planet in candidates[:_DEMO_MAX_ORIGINS]:
        origins.append(CoverageOrigin(x=planet.x, y=planet.y, base_range=_DEMO_BASE_RANGE_LY))
    if turn.nebulas:
        nebula = turn.nebulas[0]
        origins.append(
            CoverageOrigin(
                x=nebula.x,
                y=nebula.y,
                base_range=max(_DEMO_BASE_RANGE_LY, float(nebula.radius) + 20.0),
            )
        )
    return origins


def compute_map_region_demo_map(ctx: AnalyticComputeContext) -> dict:
    """Return hybrid ``regionOverlays`` for demo map rendering."""
    turn = ctx.turn
    coverage = build_hybrid_coverage(_demo_origins(turn), turn.nebulas)
    overlay = hybrid_coverage_to_overlay(
        coverage,
        kind=_DEMO_KIND,
        overlay_id=_DEMO_OVERLAY_ID,
        fill_color=_DEMO_FILL_COLOR,
        fill_opacity=_DEMO_FILL_OPACITY,
    )
    return {
        "analyticId": ANALYTIC_ID,
        "regionOverlays": [map_region_overlay_to_wire(overlay)],
        "nodes": [],
        "edges": [],
    }


def get_map_region_demo_map(
    turn: TurnInfo,
    options: TurnAnalyticsOptions | None = None,
) -> dict:
    """Convenience entry for tests and direct callers."""
    return invoke_analytic_compute(compute_map_region_demo_map, turn, options)


REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_map_region_demo_map,
    export_catalog=empty_export_catalog_for(ANALYTIC_ID),
)

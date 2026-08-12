"""Map/table compute handler for the homeworld locator analytic."""

from __future__ import annotations

from collections.abc import Callable

from api.analytics.compute_context import AnalyticComputeContext, make_analytic_compute_context
from api.analytics.homeworld_locator.baseline_ensure import (
    materialize_homeworld_candidate_view,
    read_homeworld_candidate_view,
)
from api.analytics.homeworld_locator.compute_services import resolve_homeworld_services
from api.analytics.homeworld_locator.constants import (
    ANALYTIC_ID,
    ATTRIBUTION_INFERRED,
    ATTRIBUTION_USER_ASSERTED,
)
from api.analytics.homeworld_locator.evidence_ensure import evidence_aggregate_at_shell_turn
from api.analytics.homeworld_locator.merge_above_read import merge_homeworld_evidence_above_read
from api.analytics.homeworld_locator.ownership_refine import sector_owner_sets_to_dict
from api.analytics.homeworld_locator.planet_envelopes import (
    build_homeworld_planet_envelope_overlays_for_turn,
)
from api.analytics.homeworld_locator.sector_overlays import (
    build_homeworld_sector_overlays_for_turn,
)
from api.analytics.homeworld_locator.serialization import homeworld_candidate_record_to_json
from api.analytics.homeworld_locator.types import HomeworldCandidateRecord, HomeworldCandidateView
from api.analytics.options import TurnAnalyticsOptions
from api.concepts.map_region_coverage import map_region_overlay_to_wire
from api.models.game import TurnInfo


def _wire_attribution(row: HomeworldCandidateRecord) -> str:
    """FE-compat wire field derived from ``asserted_cue`` (not durable authority)."""
    return ATTRIBUTION_USER_ASSERTED if row.asserted_cue else ATTRIBUTION_INFERRED


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
            "attribution": _wire_attribution(row),
            "assertedCue": row.asserted_cue,
            "locationAsserted": row.location_asserted,
            "isMostProbable": row.is_most_probable,
        }
        for row in view.candidates
    ]
    rows = [
        {
            **homeworld_candidate_record_to_json(row),
            "attribution": _wire_attribution(row),
            "assertedCue": row.asserted_cue,
            "locationAsserted": row.location_asserted,
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


def _homeworld_locator_wire_from_view(
    ctx: AnalyticComputeContext,
    view: HomeworldCandidateView,
) -> dict:
    """Shape map/table wire from an already-built candidate view."""
    if not view.available:
        return _view_to_wire(view)

    services = resolve_homeworld_services(ctx.exports)
    state = services.persistence.get_game_state(services.game_id)
    sector_owner_sets = None
    if state is not None:
        # Same merge-above-read as the candidate view: overlays must not re-open
        # the game-global vs aggregate storage split (ADR 0010).
        aggregate = evidence_aggregate_at_shell_turn(
            services,
            baseline_turn=state.baseline_turn,
            shell_turn=ctx.turn.settings.turn,
        )
        merged = merge_homeworld_evidence_above_read(
            game_state=state,
            aggregate=aggregate,
        )
        sector_owner_sets = sector_owner_sets_to_dict(merged.sector_owner_sets)
    overlays = build_homeworld_sector_overlays_for_turn(
        ctx.turn,
        view,
        shell_perspective=services.perspective,
        game_info=services.game_info,
        game_id=services.game_id,
        sector_owner_sets=sector_owner_sets,
    )
    # No sector wedges (suppressed, ineligible, or non-circular): planet envelopes
    # for sidebar-qualifying candidates (Show overlays filters on the client).
    if not overlays:
        overlays = build_homeworld_planet_envelope_overlays_for_turn(ctx.turn, view)
    return _view_to_wire(
        view,
        region_overlays=[map_region_overlay_to_wire(overlay) for overlay in overlays],
    )


def compute_homeworld_locator(ctx: AnalyticComputeContext) -> dict:
    """Shape map/table wire from durable homeworld state.

    REST ``get_turn_analytics`` ensures the scope through the orchestrator
    first. This handler reads that state or fails if it is missing. Direct
    callers that skip ensure use ``get_homeworld_locator``.
    """
    view = read_homeworld_candidate_view(ctx.exports, shell_turn=ctx.turn)
    return _homeworld_locator_wire_from_view(ctx, view)


def get_homeworld_locator(
    turn: TurnInfo,
    options: TurnAnalyticsOptions | None = None,
    *,
    load_turn: Callable[[int], TurnInfo | None] | None = None,
    export_services: dict[str, object] | None = None,
) -> dict:
    """Convenience entry for tests and direct callers without REST ensure."""
    ctx = make_analytic_compute_context(
        turn,
        options,
        game_id=turn.game.id,
        perspective=turn.player.id,
        load_turn=load_turn,
        export_services=export_services,
    )
    view = materialize_homeworld_candidate_view(ctx.exports, shell_turn=ctx.turn)
    return _homeworld_locator_wire_from_view(ctx, view)

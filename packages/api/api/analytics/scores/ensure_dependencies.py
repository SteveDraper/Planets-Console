"""Scores ensure edges that read fleet services for an off-mode prior.

The default edge is a final prior fleet. While Backfill earlier turns is off,
the shared off-mode rule may replace that edge with a prior fleet hop. Fleet
compute services are the seam for the prior ledger and the evidence mark.
The catch-up rule itself lives in ``api.analytics.off_mode``.
"""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import EnsureDependency, ExportScope
from api.analytics.fleet.injected_services import lookup_fleet_compute_services
from api.analytics.off_mode_prior_dependency import (
    backfill_is_enabled,
    off_mode_prior_dependency,
)

# Final prior fleet. Off-mode resolution may replace this with a prior fleet hop.
ENSURE_DEPENDENCIES: tuple[EnsureDependency, ...] = (
    EnsureDependency(analytic_id="fleet", turn_delta=-1, player_id="same", quality="final"),
)


def resolve_scores_ensure_dependencies(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    *,
    backfill_earlier_turns: bool | None = None,
) -> tuple[EnsureDependency, ...]:
    """While Backfill earlier turns is off, read an on-mark prior and do not invent holes.

    A prior that is missing or behind the mark, and still inside ``appliesFromTurn``,
    is a prior fleet hop. That hop does not schedule a scoreboard solve. An
    absent mark does not walk backward. The open turn's own scoreboard is this
    scope, not an earlier one.
    """
    if not isinstance(scope.player_id, int):
        return ENSURE_DEPENDENCIES
    services = lookup_fleet_compute_services(ctx)
    if services is None or backfill_is_enabled(services, scope.game_id, backfill_earlier_turns):
        return ENSURE_DEPENDENCIES
    turn = ctx.load_turn(scope.turn)
    if turn is None:
        return ()
    return off_mode_prior_dependency(
        ctx,
        scope,
        services,
        player_id=scope.player_id,
        turn=turn,
    )

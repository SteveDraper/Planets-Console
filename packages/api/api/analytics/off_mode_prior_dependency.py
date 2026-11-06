"""Prior-fleet ensure edge shared by fleet and scores.

The edge is a final fleet ledger one turn back for the same player. Off-mode
keeps that edge when the prior still needs a hop, and returns no edges when
it does not. The hop is a fleet file brought onto the current evidence mark.
It does not schedule a scoreboard solve. Fleet drops the edge when the player
is already eliminated on this turn.
"""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import EnsureDependency, ExportScope
from api.analytics.fleet.injected_services import (
    FleetComputeServices,
    lookup_fleet_compute_services,
)
from api.analytics.off_mode import off_mode_prior_needs_catch_up
from api.models.game import TurnInfo

# Prior fleet only. Catch-up finalization does not solve that turn's scoreboard.
# The open turn's own scoreboard is scheduled separately.
OFF_MODE_PRIOR_FLEET: tuple[EnsureDependency, ...] = (
    EnsureDependency(analytic_id="fleet", turn_delta=-1, player_id="same", quality="final"),
)


def off_mode_ensure_dependencies(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    *,
    backfill_earlier_turns: bool,
) -> tuple[EnsureDependency, ...]:
    """Shared prior-fleet edge for this scope, or no edges.

    A non-integer player, missing fleet services, or Backfill earlier turns
    keeps the edge. While backfill is off, a stored turn keeps that same edge
    only when ``scope.turn - 1`` still needs a hop inside ``appliesFromTurn``.
    A turn that is not stored, or a prior that does not need a hop, returns
    no edges. An absent mark does not walk backward. The open turn's own
    scoreboard is this scope, not an earlier one.
    """
    if not isinstance(scope.player_id, int):
        return OFF_MODE_PRIOR_FLEET
    services = lookup_fleet_compute_services(ctx)
    if services is None or backfill_earlier_turns:
        return OFF_MODE_PRIOR_FLEET
    turn = ctx.load_turn(scope.turn)
    if turn is None:
        return ()
    return _off_mode_prior_dependency(
        ctx,
        scope,
        services,
        player_id=scope.player_id,
        turn=turn,
    )


def _off_mode_prior_dependency(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    services: FleetComputeServices,
    *,
    player_id: int,
    turn: TurnInfo,
) -> tuple[EnsureDependency, ...]:
    """Same prior-fleet edge when ``scope.turn - 1`` still needs a hop.

    Reads that prior ledger and the player's evidence mark, then applies
    ``off_mode_prior_needs_catch_up``. Returns no edges when the prior does
    not need a hop.
    """
    prior = services.persistence.get_ledger(
        scope.game_id,
        scope.perspective,
        scope.turn - 1,
        player_id,
    )
    mark = services.persistence.evidence_mark(scope.game_id, scope.perspective, player_id)
    if not off_mode_prior_needs_catch_up(
        turn_number=scope.turn,
        settings=turn.settings,
        load_turn=ctx.load_turn,
        prior_ledger=prior,
        mark=mark,
    ):
        return ()
    return OFF_MODE_PRIOR_FLEET

"""Prior-fleet ensure edge shared by fleet and scores.

The edge is a final fleet ledger one turn back for the same player. The hop is
a fleet file brought onto the current evidence mark. It does not schedule a
scoreboard solve. ``off_mode_ensure_dependencies`` decides per scope whether
the edge applies.
"""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import EnsureDependency, ExportScope
from api.analytics.fleet.eliminated_player import player_has_on_walk_root
from api.analytics.fleet.injected_services import (
    FleetComputeServices,
    lookup_fleet_compute_services,
)
from api.analytics.off_mode import PriorFleetRelation, off_mode_prior_relation
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

    * A non-integer player keeps the edge.
    * Backfill earlier turns on: the edge applies unless the player is
      eliminated on ``scope.turn``, which has no on-walk and so no prior-fleet
      dependency. A turn that cannot be loaded keeps the edge, because
      elimination cannot be shown. The dependency walk then reports a prior
      turn that is not stored, or stops at the ensure floor.
    * Backfill earlier turns off: missing fleet services keep the edge. Without
      a loadable ``scope.turn`` there are no settings to classify the hop, so
      there are no edges. Otherwise the edge applies only when
      ``scope.turn - 1`` still needs a hop inside ``appliesFromTurn``. An absent
      mark does not walk backward. This branch does not consult elimination; the
      fleet export applies that check before calling here in both modes.
    """
    if not isinstance(scope.player_id, int):
        return OFF_MODE_PRIOR_FLEET
    if backfill_earlier_turns:
        turn = ctx.load_turn(scope.turn)
        has_on_walk_root = turn is None or player_has_on_walk_root(turn, scope.player_id)
        return OFF_MODE_PRIOR_FLEET if has_on_walk_root else ()
    services = lookup_fleet_compute_services(ctx)
    if services is None:
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
    ``off_mode_prior_relation``. The prior host turn is loaded only when
    stored-ness can change that result. Returns no edges when the prior is
    not a hop.
    """
    prior = services.persistence.get_ledger(
        scope.game_id,
        scope.perspective,
        scope.turn - 1,
        player_id,
    )
    mark = services.persistence.evidence_mark(scope.game_id, scope.perspective, player_id)

    def load_prior_turn() -> TurnInfo | None:
        return ctx.load_turn(scope.turn - 1)

    relation = off_mode_prior_relation(
        turn_number=scope.turn,
        settings=turn.settings,
        load_prior_turn=load_prior_turn,
        prior_ledger=prior,
        mark=mark,
    )
    if relation is not PriorFleetRelation.HOP_NEEDED:
        return ()
    return OFF_MODE_PRIOR_FLEET

"""Prior-fleet edge for off-mode catch-up.

Fleet and scores ensure resolvers share this edge. Whether that prior needs a
hop is ``off_mode_prior_needs_catch_up``, which reads ``off_mode_prior_relation``.
The hop is a fleet file brought onto the current evidence mark. It does not
schedule a scoreboard solve. Resolvers still decide player scope, elimination,
and whether backfill is on.
"""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import EnsureDependency, ExportScope
from api.analytics.fleet.injected_services import FleetComputeServices
from api.analytics.off_mode import off_mode_prior_needs_catch_up
from api.models.game import TurnInfo

# Prior fleet only. Catch-up finalization does not solve that turn's scoreboard.
# The open turn's own scoreboard is scheduled separately.
OFF_MODE_PRIOR_FLEET: tuple[EnsureDependency, ...] = (
    EnsureDependency(analytic_id="fleet", turn_delta=-1, player_id="same", quality="final"),
)


def off_mode_prior_dependency(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
    services: FleetComputeServices,
    *,
    player_id: int,
    turn: TurnInfo,
) -> tuple[EnsureDependency, ...]:
    """Prior-fleet edge when ``scope.turn - 1`` still needs a hop.

    Reads that prior ledger and the player's evidence mark, then applies
    ``off_mode_prior_needs_catch_up``.
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

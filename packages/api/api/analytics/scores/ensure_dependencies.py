"""Scores ensure edges, including the off-mode stamped fleet hop.

Lives outside the scores export catalog so mark readers do not import fleet.
"""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.export_types import EnsureDependency, ExportScope
from api.analytics.fleet.injected_services import lookup_fleet_compute_services
from api.analytics.off_mode_prior_dependency import off_mode_prior_dependency


def resolve_scores_ensure_dependencies(
    ctx: AnalyticQueryContext,
    scope: ExportScope,
) -> tuple[EnsureDependency, ...]:
    """While Backfill earlier turns is off, read an on-mark prior and do not invent holes.

    A prior that is missing or behind the mark, and still inside ``appliesFromTurn``,
    is a stamped fleet hop. That hop does not schedule a scoreboard solve. An
    absent mark does not walk backward. The open turn's own scoreboard is this
    scope, not an earlier one.
    """
    from api.analytics.scores.exports import ENSURE_DEPENDENCIES

    if not isinstance(scope.player_id, int):
        return ENSURE_DEPENDENCIES
    services = lookup_fleet_compute_services(ctx)
    if services is None or services.persistence.backfill_earlier_turns_enabled(scope.game_id):
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

"""A scoreboard row's prior fleet, and whether the row awaits its walk.

Scores at turn N reads fleet at N-1 as its prior, except at or below the
analytic export ensure floor, where there is none. With **Backfill earlier
turns** on, the walk is what makes that prior ensure-final, so a row whose
prior is not ensure-final must submit its walk rather than show a stored row.
"""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.eliminated_player import player_has_on_walk_root
from api.analytics.fleet.injected_services import lookup_fleet_compute_services
from api.compute.scope import ComputeScope
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.models.game import GameSettings, TurnInfo


def prior_fleet_compute_scope(
    *,
    game_id: int,
    perspective: int,
    turn: int,
    player_id: int,
    settings: GameSettings,
) -> ComputeScope | None:
    """Fleet scope for scores@N prior (fleet@(N-1)), or None when not applicable."""
    if turn <= accelerated_ensure_floor(settings, turn):
        return None
    return ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=game_id,
        perspective=perspective,
        turn=turn - 1,
        player_id=player_id,
    )


def row_awaits_its_walk(
    ctx: AnalyticQueryContext | None,
    turn: TurnInfo,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
) -> bool:
    """Whether this scoreboard row must submit its walk rather than show a stored row.

    True with **Backfill earlier turns** on when the row's prior fleet is not
    ensure-final under the current mark: the walk is what refreshes it, and a
    stored row computed from the old prior would stand in for it. False with
    the setting off, without fleet services, for a player with no on-walk
    (eliminated on this turn), and for a turn at or below the ensure floor,
    which has no prior fleet.
    """
    if ctx is None:
        return False
    services = lookup_fleet_compute_services(ctx)
    if services is None or not player_has_on_walk_root(turn, player_id):
        return False
    prior = prior_fleet_compute_scope(
        game_id=game_id,
        perspective=perspective,
        turn=turn.settings.turn,
        player_id=player_id,
        settings=turn.settings,
    )
    if prior is None or not ctx.backfill_earlier_turns_enabled():
        return False
    return not services.persistence.has_final_ledger(game_id, perspective, prior.turn, player_id)

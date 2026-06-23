"""Core Fleet turn analytic (registration shell)."""

from api.analytics.catalog import catalog_entry
from api.analytics.compute_context import AnalyticComputeContext, invoke_analytic_compute
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.registration import TurnAnalyticRegistration
from api.models.game import TurnInfo

ANALYTIC_ID = "fleet"


def _fleet_players(turn: TurnInfo) -> list[dict[str, object]]:
    seen: set[int] = set()
    players: list[dict[str, object]] = []
    for player in (turn.player, *turn.players):
        if player.id in seen:
            continue
        seen.add(player.id)
        players.append(
            {
                "playerId": player.id,
                "playerName": player.username,
                "records": [],
            }
        )
    return players


def compute_fleet(ctx: AnalyticComputeContext) -> dict:
    """Return an empty per-player fleet ledger scaffold for the shell turn."""
    return {
        "analyticId": ANALYTIC_ID,
        "players": _fleet_players(ctx.turn),
    }


def get_fleet(turn: TurnInfo) -> dict:
    """Convenience entry for tests and direct callers."""
    return invoke_analytic_compute(compute_fleet, turn)


REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_fleet,
    export_catalog=empty_export_catalog_for(ANALYTIC_ID),
)

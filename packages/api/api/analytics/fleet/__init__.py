"""Core Fleet turn analytic."""

from api.analytics.catalog import catalog_entry
from api.analytics.compute_context import AnalyticComputeContext, invoke_analytic_compute
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.fleet.chain import get_or_materialize_fleet_snapshot
from api.analytics.fleet.compute_services import resolve_fleet_compute_services
from api.analytics.fleet.serialization import fleet_acquisition_ledger_to_json
from api.analytics.fleet.types import FleetAcquisitionLedger
from api.analytics.registration import TurnAnalyticRegistration
from api.analytics.turn_roster import iter_turn_players
from api.models.game import TurnInfo

ANALYTIC_ID = "fleet"


def _ephemeral_fleet_players(turn: TurnInfo) -> list[dict[str, object]]:
    return [
        fleet_acquisition_ledger_to_json(
            FleetAcquisitionLedger(player_id=player.id, player_name=player.username)
        )
        for player in iter_turn_players(turn)
    ]


def _fleet_snapshot_to_compute_wire(snapshot) -> dict[str, object]:
    return {
        "analyticId": snapshot.analytic_id,
        "players": [
            fleet_acquisition_ledger_to_json(player_ledger) for player_ledger in snapshot.players
        ],
    }


def compute_fleet(ctx: AnalyticComputeContext) -> dict:
    """Return the fleet acquisition ledger for the shell turn."""
    services = resolve_fleet_compute_services(ctx)
    if services is None:
        return {
            "analyticId": ANALYTIC_ID,
            "players": _ephemeral_fleet_players(ctx.turn),
        }
    snapshot = get_or_materialize_fleet_snapshot(
        services.persistence,
        services.game_id,
        services.perspective,
        ctx.turn,
        load_turn=services.load_turn,
    )
    return _fleet_snapshot_to_compute_wire(snapshot)


def get_fleet(turn: TurnInfo) -> dict:
    """Convenience entry for tests and direct callers without persistence."""
    return invoke_analytic_compute(compute_fleet, turn)


REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_fleet,
    export_catalog=empty_export_catalog_for(ANALYTIC_ID),
)

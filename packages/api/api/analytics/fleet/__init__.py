"""Core Fleet turn analytic."""

from api.analytics.catalog import catalog_entry
from api.analytics.compute_context import AnalyticComputeContext, invoke_analytic_compute
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.fleet.chain import get_or_materialize_fleet_snapshot
from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.fleet.compute_services import (
    build_ephemeral_fleet_compute_services,
    resolve_fleet_compute_services,
)
from api.analytics.fleet.serialization import fleet_turn_snapshot_to_compute_wire
from api.analytics.registration import TurnAnalyticRegistration
from api.models.game import TurnInfo


def compute_fleet(ctx: AnalyticComputeContext) -> dict:
    """Return the fleet acquisition ledger for the shell turn."""
    services = resolve_fleet_compute_services(ctx)
    snapshot = get_or_materialize_fleet_snapshot(
        services.persistence,
        services.game_id,
        services.perspective,
        ctx.turn,
        load_turn=services.load_turn,
    )
    return fleet_turn_snapshot_to_compute_wire(snapshot)


def get_fleet(turn: TurnInfo) -> dict:
    """Convenience entry for tests and direct callers without durable persistence."""
    return invoke_analytic_compute(
        compute_fleet,
        turn,
        export_services={ANALYTIC_ID: build_ephemeral_fleet_compute_services(turn)},
    )


REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_fleet,
    export_catalog=empty_export_catalog_for(ANALYTIC_ID),
)

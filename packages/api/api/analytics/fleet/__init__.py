"""Core Fleet turn analytic."""

from api.analytics.catalog import catalog_entry
from api.analytics.compute_context import AnalyticComputeContext, invoke_analytic_compute
from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.registration import TurnAnalyticRegistration
from api.models.game import TurnInfo


def compute_fleet(ctx: AnalyticComputeContext) -> dict:
    """Return the fleet acquisition ledger for the shell turn."""
    from api.analytics.fleet.chain import get_or_materialize_fleet_snapshot
    from api.analytics.fleet.compute_services import resolve_fleet_compute_services
    from api.analytics.fleet.serialization import fleet_turn_snapshot_to_compute_wire

    services = resolve_fleet_compute_services(ctx)
    snapshot = get_or_materialize_fleet_snapshot(
        services.persistence,
        services.game_id,
        services.perspective,
        ctx.turn,
        load_turn=services.load_turn,
        inference_materialization=services.inference_materialization,
        query_context=ctx.exports,
    )
    return fleet_turn_snapshot_to_compute_wire(snapshot)


def get_fleet(turn: TurnInfo) -> dict:
    """Convenience entry for tests and direct callers without durable persistence."""
    from api.analytics.fleet.compute_services import build_ephemeral_fleet_compute_services

    return invoke_analytic_compute(
        compute_fleet,
        turn,
        export_services={ANALYTIC_ID: build_ephemeral_fleet_compute_services(turn)},
    )


def _load_fleet_export_catalog():
    from api.analytics.fleet.exports import EXPORT_CATALOG

    return EXPORT_CATALOG


def iter_fleet_table_stream(
    turn: TurnInfo,
    player_ids: tuple[int, ...],
    *,
    game_id: int,
    perspective: int,
    fleet_services,
    persistence,
    scheduler=None,
):
    """Yield NDJSON wire events for fleet table materialization on one stream."""
    from api.analytics.fleet.fleet_table_stream_rows import iter_fleet_table_stream_events

    yield from iter_fleet_table_stream_events(
        turn,
        player_ids,
        game_id=game_id,
        perspective=perspective,
        fleet_services=fleet_services,
        persistence=persistence,
        scheduler=scheduler,
    )


REGISTRATION = TurnAnalyticRegistration(
    catalog_entry=catalog_entry(ANALYTIC_ID),
    compute=compute_fleet,
    export_catalog_loader=_load_fleet_export_catalog,
)

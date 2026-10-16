"""Prior-turn active ships for one counterparty, read from fleet persistence."""

from __future__ import annotations

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.compute_services import lookup_fleet_compute_services
from api.analytics.fleet.types import CounterpartyFleetLoader, FleetShipRecord


def counterparty_fleet_loader(
    query_context: AnalyticQueryContext | None,
    *,
    game_id: int,
    perspective: int,
    turn_number: int,
) -> CounterpartyFleetLoader | None:
    """Load each donor's prior-turn active ships through fleet persistence.

    Returns None when there is no query context, the turn is the opening turn,
    or fleet services are absent. The caller then keeps the existing search.
    """
    if query_context is None or turn_number <= 1:
        return None
    services = lookup_fleet_compute_services(query_context)
    if services is None:
        return None
    persistence = services.persistence
    prior_turn = turn_number - 1

    def load(player_id: int) -> tuple[FleetShipRecord, ...]:
        persisted = persistence.get_ledger(game_id, perspective, prior_turn, player_id)
        if persisted is None:
            return ()
        return tuple(
            record for record in persisted.ledger.records if record.disposition == "active"
        )

    return load

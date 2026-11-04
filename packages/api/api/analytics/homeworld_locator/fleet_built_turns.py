"""Known fleet ``built_turn`` ages from a persisted ledger."""

from __future__ import annotations

from api.analytics.fleet.field_constraints import known_ship_built_turns
from api.analytics.fleet.types import PersistedFleetLedger


def built_turns_from_persisted_ledger(persisted: PersistedFleetLedger) -> dict[int, int]:
    """Known ``ship_id -> built_turn`` from one persisted fleet ledger."""
    return known_ship_built_turns(persisted.ledger.records)

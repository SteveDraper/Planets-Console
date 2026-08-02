"""Extract fleet ``built_turn`` ages for ownership evidence (#269).

Sources: orchestrator ``DependencyOutputs`` wires, or final on-disk ledgers after
ENSURE (sync export ensure path).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from api.analytics.fleet.field_constraints import (
    known_built_turn_value,
    known_positive_component_id,
)
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.serialization import persisted_fleet_ledger_from_json
from api.analytics.fleet.types import PersistedFleetLedger
from api.compute.wire import DependencyOutputs


def built_turns_from_persisted_ledger(persisted: PersistedFleetLedger) -> dict[int, int]:
    """Known ``ship_id -> built_turn`` from one persisted fleet ledger."""
    built_turns: dict[int, int] = {}
    for record in persisted.ledger.records:
        ship_id = known_positive_component_id(record.fields.ship_id)
        built_turn = known_built_turn_value(record)
        if ship_id is not None and built_turn is not None:
            built_turns[ship_id] = built_turn
    return built_turns


def fleet_built_turns_from_dependency_outputs(
    dependency_outputs: DependencyOutputs,
) -> dict[int, int]:
    """Merge known ``ship_id -> built_turn`` from all final fleet dependency wires."""
    built_turns: dict[int, int] = {}
    for scope, wire in dependency_outputs.as_mapping().items():
        if scope.analytic_id != "fleet":
            continue
        if not isinstance(wire, dict):
            continue
        persisted_wire = wire.get("persistedLedgerWire")
        if not isinstance(persisted_wire, dict):
            continue
        persisted = persisted_fleet_ledger_from_json(persisted_wire)
        built_turns.update(built_turns_from_persisted_ledger(persisted))
    return built_turns


def fleet_built_turns_from_final_ledgers(
    persistence: FleetSnapshotPersistenceService,
    *,
    game_id: int,
    perspective: int,
    turn_number: int,
    player_ids: Sequence[int],
) -> dict[int, int]:
    """Merge ``built_turn`` ages from final on-disk fleet ledgers for ``player_ids``.

    Call only after homeworld ENSURE has satisfied ``fleet@N`` per roster player.
    Non-final or missing ledgers are skipped (scoreboard max-age remains the fallback
    inside ownership refine).
    """
    built_turns: dict[int, int] = {}
    for player_id in player_ids:
        if not persistence.has_final_ledger(game_id, perspective, turn_number, player_id):
            continue
        persisted = persistence.get_ledger(game_id, perspective, turn_number, player_id)
        if persisted is None:
            continue
        built_turns.update(built_turns_from_persisted_ledger(persisted))
    return built_turns


def coerce_fleet_built_turns_map(raw: Mapping[object, object] | None) -> dict[int, int]:
    """Normalize job-wire / caller maps (int or digit-string ship ids) to ``dict[int, int]``."""
    if raw is None:
        return {}
    built_turn_map: dict[int, int] = {}
    for ship_id, built_turn in raw.items():
        if not isinstance(built_turn, int):
            continue
        if isinstance(ship_id, int):
            built_turn_map[ship_id] = built_turn
        elif isinstance(ship_id, str) and ship_id.isdigit():
            built_turn_map[int(ship_id)] = built_turn
    return built_turn_map

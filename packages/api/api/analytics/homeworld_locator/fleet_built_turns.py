"""Extract fleet ``built_turn`` ages from orchestrator dependency wires (#269)."""

from __future__ import annotations

from api.analytics.fleet.field_constraints import (
    known_built_turn_value,
    known_positive_component_id,
)
from api.analytics.fleet.serialization import persisted_fleet_ledger_from_json
from api.compute.wire import DependencyOutputs


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
        for record in persisted.ledger.records:
            ship_id = known_positive_component_id(record.fields.ship_id)
            built_turn = known_built_turn_value(record)
            if ship_id is not None and built_turn is not None:
                built_turns[ship_id] = built_turn
    return built_turns

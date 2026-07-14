"""Fleet export composition branch: component histograms and max tech levels."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.export_types import ExportScope
from api.analytics.fleet.belief_set_components import component_ids_for_record_on_axis
from api.analytics.fleet.export_scope import ledgers_for_scope
from api.analytics.fleet.max_tech import max_tech_by_axis_from_fleet_records
from api.analytics.fleet.types import (
    FleetShipRecord,
    FleetTurnSnapshot,
)
from api.models.game import TurnInfo


@dataclass(frozen=True, slots=True)
class _CompositionAxisSpec:
    field_name: str
    histogram_output_key: str


_COMPOSITION_AXIS_SPECS: tuple[_CompositionAxisSpec, ...] = (
    _CompositionAxisSpec("hull", "hullTypes"),
    _CompositionAxisSpec("engine", "engineTypes"),
    _CompositionAxisSpec("beams", "beamTypes"),
    _CompositionAxisSpec("launchers", "launcherTypes"),
)


def _increment_histogram(histogram: dict[str, int], component_id: int) -> None:
    key = str(component_id)
    histogram[key] = histogram.get(key, 0) + 1


def _active_records_for_scope(
    snapshot: FleetTurnSnapshot,
    scope: ExportScope,
) -> list[FleetShipRecord]:
    records: list[FleetShipRecord] = []
    for ledger in ledgers_for_scope(snapshot, scope):
        for record in ledger.records:
            if record.disposition == "active":
                records.append(record)
    return records


def _empty_fleet_composition_branch() -> dict[str, object]:
    return {
        "hullTypes": {},
        "engineTypes": {},
        "beamTypes": {},
        "launcherTypes": {},
        "torpedoTypesLoaded": {},
        "maxTechLevel": {},
    }


def build_fleet_composition_branch(
    snapshot: FleetTurnSnapshot,
    scope: ExportScope,
    *,
    turn: TurnInfo,
) -> dict[str, object]:
    """Per-player composition histograms and max tech levels.

    When ``scope.player_id`` is unset, returns an empty branch rather than
    aggregating across all players. Unscoped composition paths are rejected at
    query time; this keeps materialized trees safe for unscoped meta reads.

    Belief-set histograms union known fitted component ids with every fleet build
    option set on active rows (consistent tuples only, no per-field Cartesian
    product).
    """
    if scope.player_id is None:
        return _empty_fleet_composition_branch()

    active_records = _active_records_for_scope(snapshot, scope)
    histograms: dict[str, dict[str, int]] = {
        axis.histogram_output_key: {} for axis in _COMPOSITION_AXIS_SPECS
    }

    for record in active_records:
        for axis in _COMPOSITION_AXIS_SPECS:
            histogram = histograms[axis.histogram_output_key]
            for component_id in component_ids_for_record_on_axis(record, axis.field_name):
                _increment_histogram(histogram, component_id)

    return {
        **histograms,
        "torpedoTypesLoaded": {},
        "maxTechLevel": max_tech_by_axis_from_fleet_records(active_records, turn),
    }

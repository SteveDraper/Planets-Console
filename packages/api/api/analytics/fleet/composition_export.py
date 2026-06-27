"""Fleet export composition branch: component histograms and max tech levels."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from api.analytics.export_types import ExportScope
from api.analytics.fleet.export_scope import ledgers_for_scope
from api.analytics.fleet.types import (
    FleetFieldConstraint,
    FleetFieldKnown,
    FleetShipRecord,
    FleetTurnSnapshot,
)
from api.concepts.turn_component_catalog import (
    beams_by_id,
    engines_by_id,
    hulls_by_id,
    torpedos_by_id,
)
from api.models.game import TurnInfo


@dataclass(frozen=True, slots=True)
class _CompositionAxisSpec:
    field_name: str
    histogram_output_key: str | None
    max_tech_key: str
    catalog_key: str


_COMPOSITION_AXIS_SPECS: tuple[_CompositionAxisSpec, ...] = (
    _CompositionAxisSpec("hull", "hullTypes", "hulls", "hulls"),
    _CompositionAxisSpec("beams", "beamTypes", "beams", "beams"),
    _CompositionAxisSpec("launchers", "launcherTypes", "launchers", "launchers"),
    _CompositionAxisSpec("engine", None, "engines", "engines"),
)


class _TechLevelComponent(Protocol):
    techlevel: int


def _known_positive_component_id(field: FleetFieldConstraint) -> int | None:
    if not isinstance(field, FleetFieldKnown):
        return None
    value = field.value
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    return value


def _increment_component_histogram(
    histogram: dict[str, int],
    field: FleetFieldConstraint,
) -> None:
    component_id = _known_positive_component_id(field)
    if component_id is None:
        return
    key = str(component_id)
    histogram[key] = histogram.get(key, 0) + 1


def _max_tech_level(
    component_ids: Iterable[int],
    catalog: dict[int, _TechLevelComponent],
) -> int | None:
    max_level: int | None = None
    for component_id in component_ids:
        component = catalog.get(component_id)
        if component is None:
            continue
        if max_level is None or component.techlevel > max_level:
            max_level = component.techlevel
    return max_level


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


def _component_ids_for_axis(
    axis: _CompositionAxisSpec,
    histograms: dict[str, dict[str, int]],
    engine_ids: list[int],
) -> Iterable[int]:
    if axis.histogram_output_key is None:
        return engine_ids
    return (int(key) for key in histograms[axis.histogram_output_key])


def _empty_fleet_composition_branch() -> dict[str, object]:
    return {
        "hullTypes": {},
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
    """
    if scope.player_id is None:
        return _empty_fleet_composition_branch()

    histograms: dict[str, dict[str, int]] = {
        axis.histogram_output_key: {}
        for axis in _COMPOSITION_AXIS_SPECS
        if axis.histogram_output_key is not None
    }
    engine_ids: list[int] = []

    for record in _active_records_for_scope(snapshot, scope):
        for axis in _COMPOSITION_AXIS_SPECS:
            field = getattr(record.fields, axis.field_name)
            if axis.histogram_output_key is None:
                component_id = _known_positive_component_id(field)
                if component_id is not None:
                    engine_ids.append(component_id)
            else:
                _increment_component_histogram(histograms[axis.histogram_output_key], field)

    catalogs: dict[str, dict[int, _TechLevelComponent]] = {
        "hulls": hulls_by_id(turn),
        "engines": engines_by_id(turn),
        "beams": beams_by_id(turn),
        "launchers": torpedos_by_id(turn),
    }

    max_tech_level: dict[str, int] = {}
    for axis in _COMPOSITION_AXIS_SPECS:
        if axis_max := _max_tech_level(
            _component_ids_for_axis(axis, histograms, engine_ids),
            catalogs[axis.catalog_key],
        ):
            max_tech_level[axis.max_tech_key] = axis_max

    return {
        **histograms,
        "torpedoTypesLoaded": {},
        "maxTechLevel": max_tech_level,
    }

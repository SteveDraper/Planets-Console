"""Fleet export composition branch: component histograms and max tech levels."""

from __future__ import annotations

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


def _max_tech_level_for_histogram(
    histogram: dict[str, int],
    catalog: dict[int, _TechLevelComponent],
) -> int | None:
    max_level: int | None = None
    for key in histogram:
        component = catalog.get(int(key))
        if component is None:
            continue
        if max_level is None or component.techlevel > max_level:
            max_level = component.techlevel
    return max_level


def _max_tech_level_for_component_ids(
    component_ids: list[int],
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


def build_fleet_composition_branch(
    snapshot: FleetTurnSnapshot,
    scope: ExportScope,
    *,
    turn: TurnInfo,
) -> dict[str, object]:
    hull_types: dict[str, int] = {}
    beam_types: dict[str, int] = {}
    launcher_types: dict[str, int] = {}
    engine_ids: list[int] = []

    for record in _active_records_for_scope(snapshot, scope):
        _increment_component_histogram(hull_types, record.fields.hull)
        _increment_component_histogram(beam_types, record.fields.beams)
        _increment_component_histogram(launcher_types, record.fields.launchers)
        engine_id = _known_positive_component_id(record.fields.engine)
        if engine_id is not None:
            engine_ids.append(engine_id)

    hull_catalog = hulls_by_id(turn)
    engine_catalog = engines_by_id(turn)
    beam_catalog = beams_by_id(turn)
    torp_catalog = torpedos_by_id(turn)

    max_tech_level: dict[str, int] = {}
    if hull_max := _max_tech_level_for_histogram(hull_types, hull_catalog):
        max_tech_level["hulls"] = hull_max
    if engine_max := _max_tech_level_for_component_ids(engine_ids, engine_catalog):
        max_tech_level["engines"] = engine_max
    if launcher_max := _max_tech_level_for_histogram(launcher_types, torp_catalog):
        max_tech_level["launchers"] = launcher_max
    if beam_max := _max_tech_level_for_histogram(beam_types, beam_catalog):
        max_tech_level["beams"] = beam_max

    return {
        "hullTypes": hull_types,
        "beamTypes": beam_types,
        "launcherTypes": launcher_types,
        "torpedoTypesLoaded": {},
        "maxTechLevel": max_tech_level,
    }

"""Max component tech levels from fleet ship records and turn catalogs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

from api.analytics.fleet.belief_set_components import component_ids_for_axis_from_records
from api.analytics.fleet.types import FleetShipRecord
from api.concepts.turn_component_catalog import (
    beams_by_id,
    engines_by_id,
    hulls_by_id,
    torpedos_by_id,
)
from api.models.game import TurnInfo

# Export / inference keys match tier-policy filter axis names.
MAX_TECH_AXIS_KEYS: tuple[str, ...] = ("hulls", "engines", "beams", "launchers")

_AXIS_FIELD_BY_KEY: dict[str, str] = {
    "hulls": "hull",
    "engines": "engine",
    "beams": "beams",
    "launchers": "launchers",
}


class _TechLevelComponent(Protocol):
    techlevel: int


def max_tech_level_for_component_ids(
    component_ids: Iterable[int],
    catalog: Mapping[int, _TechLevelComponent],
) -> int | None:
    """Highest ``techlevel`` among ``component_ids`` present in ``catalog``."""
    max_level: int | None = None
    for component_id in component_ids:
        component = catalog.get(component_id)
        if component is None:
            continue
        if max_level is None or component.techlevel > max_level:
            max_level = component.techlevel
    return max_level


def max_tech_in_turn_catalog(turn: TurnInfo, axis_key: str) -> int | None:
    """Highest techlevel present in the turn catalog for one export/filter axis."""
    catalogs = _catalogs_by_axis(turn)
    catalog = catalogs.get(axis_key)
    if catalog is None or not catalog:
        return None
    return max(component.techlevel for component in catalog.values())


def max_tech_by_axis_from_fleet_records(
    records: Iterable[FleetShipRecord],
    turn: TurnInfo,
    *,
    active_only: bool = True,
    option_set_mass_threshold: float | None = None,
) -> dict[str, int]:
    """Per-axis max tech from fleet records (keys: hulls/engines/beams/launchers).

    Known positive fitted components always contribute. When
    ``option_set_mass_threshold`` is set, only option sets whose per-row softmax
    probability meets that floor contribute soft ids (#253). Axes with no
    contributing ids (or ids missing from the turn catalog) are omitted.
    """
    catalogs = _catalogs_by_axis(turn)
    record_list = list(records)
    result: dict[str, int] = {}
    for axis_key in MAX_TECH_AXIS_KEYS:
        field_name = _AXIS_FIELD_BY_KEY[axis_key]
        component_ids = component_ids_for_axis_from_records(
            record_list,
            field_name,
            active_only=active_only,
            option_set_mass_threshold=option_set_mass_threshold,
        )
        axis_max = max_tech_level_for_component_ids(component_ids, catalogs[axis_key])
        if axis_max is not None:
            result[axis_key] = axis_max
    return result


def _catalogs_by_axis(turn: TurnInfo) -> dict[str, dict[int, _TechLevelComponent]]:
    return {
        "hulls": hulls_by_id(turn),
        "engines": engines_by_id(turn),
        "beams": beams_by_id(turn),
        "launchers": torpedos_by_id(turn),
    }

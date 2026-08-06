"""Wire-only fleet ship military estimates for table/stream records.

Not persisted on the durable ledger. Resolves a construction fit from locks,
display-default option set, and ``default_build_components`` fill policy, then
scores via the shared ship-build military helper.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.fleet.display_default_option_set import (
    resolve_display_default_build_option_set,
)
from api.analytics.fleet.field_constraints import known_positive_component_id
from api.analytics.fleet.observation_option_locks import (
    ObservationComponentLocks,
    observation_locks_from_record,
)
from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetFieldConstraint,
    FleetFieldKnown,
    FleetShipRecord,
)
from api.concepts.hulls import is_generic_freighter_sentinel_hull_id
from api.concepts.ship_build_military import (
    default_build_components,
    ship_build_military_score_delta_2x,
)
from api.concepts.turn_component_catalog import (
    beams_by_id,
    engines_by_id,
    hulls_by_id,
    torpedos_by_id,
)
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo

@dataclass(frozen=True, slots=True)
class ResolvedShipConstructionFit:
    """Catalog parts and counts ready for ``ship_build_military_score_delta_2x``."""

    hull: Hull
    engine: Engine
    beam: Beam | None
    torpedo: Torpedo | None
    beam_count: int
    launcher_count: int


def fleet_ship_military_estimate_2x(
    record: FleetShipRecord,
    *,
    turn: TurnInfo,
) -> int | None:
    """Return scaled military estimate for one record, or None when not estimable.

    Known parts come from locked fields and the display-default build option set.
    Unknown beam/tube slots are treated as full at minimal-tech catalog parts;
    unknown engines use the same default picker for API uniformity with the scorer.
    Loaded ammo is excluded (owned by the shared construction helper).
    """
    option_set = resolve_display_default_build_option_set(record)
    locks = observation_locks_from_record(record)
    hull_id = _resolve_hull_id(locks=locks, option_set=option_set)
    if hull_id is None:
        return None
    if is_generic_freighter_sentinel_hull_id(hull_id):
        return 0

    fit = _resolve_fit_for_hull(
        record,
        turn=turn,
        hull_id=hull_id,
        option_set=option_set,
        locks=locks,
    )
    if fit is None:
        return None
    return ship_build_military_score_delta_2x(
        fit.hull,
        fit.engine,
        fit.beam,
        fit.torpedo,
        beam_count=fit.beam_count,
        launcher_count=fit.launcher_count,
    )


def resolve_ship_construction_fit(
    record: FleetShipRecord,
    *,
    turn: TurnInfo,
) -> ResolvedShipConstructionFit | None:
    """Resolve catalog construction inputs for a military estimate.

    Returns ``None`` when not estimable, including the generic-freighter sentinel
    (callers that need score ``0`` for that sentinel should use
    :func:`fleet_ship_military_estimate_2x`).
    """
    option_set = resolve_display_default_build_option_set(record)
    locks = observation_locks_from_record(record)
    hull_id = _resolve_hull_id(locks=locks, option_set=option_set)
    if hull_id is None or is_generic_freighter_sentinel_hull_id(hull_id):
        return None
    return _resolve_fit_for_hull(
        record,
        turn=turn,
        hull_id=hull_id,
        option_set=option_set,
        locks=locks,
    )


def _resolve_fit_for_hull(
    record: FleetShipRecord,
    *,
    turn: TurnInfo,
    hull_id: int,
    option_set: FleetBuildOptionSet | None,
    locks: ObservationComponentLocks,
) -> ResolvedShipConstructionFit | None:
    turn_hulls = hulls_by_id(turn)
    turn_engines = engines_by_id(turn)
    turn_beams = beams_by_id(turn)
    turn_torpedos = torpedos_by_id(turn)

    hull = turn_hulls.get(hull_id)
    if hull is None:
        return None

    defaults = default_build_components(
        engines_by_id=turn_engines,
        beams_by_id=turn_beams,
        torpedos_by_id=turn_torpedos,
    )

    engine = _resolve_engine(
        record,
        option_set=option_set,
        locks_engine_id=locks.engine_id,
        engines_by_id=turn_engines,
        default_engine=defaults.engine,
    )
    if engine is None:
        return None

    beam, beam_count = _resolve_weapon_fit(
        record_field=record.fields.beams,
        option_set_id=option_set.beam_id if option_set is not None else None,
        option_set_count=option_set.beam_count if option_set is not None else None,
        locks_id=locks.beam_id,
        locks_count=locks.beam_count,
        slot_capacity=hull.beams,
        components_by_id=turn_beams,
        default_component=defaults.beam,
    )
    if beam_count is None:
        return None

    torpedo, launcher_count = _resolve_weapon_fit(
        record_field=record.fields.launchers,
        option_set_id=option_set.torp_id if option_set is not None else None,
        option_set_count=option_set.launcher_count if option_set is not None else None,
        locks_id=locks.torp_id,
        locks_count=locks.launcher_count,
        slot_capacity=hull.launchers,
        components_by_id=turn_torpedos,
        default_component=defaults.torpedo,
    )
    if launcher_count is None:
        return None

    return ResolvedShipConstructionFit(
        hull=hull,
        engine=engine,
        beam=beam,
        torpedo=torpedo,
        beam_count=beam_count,
        launcher_count=launcher_count,
    )


def _resolve_hull_id(
    *,
    locks: ObservationComponentLocks,
    option_set: FleetBuildOptionSet | None,
) -> int | None:
    if locks.hull_id is not None:
        return locks.hull_id
    if option_set is not None and option_set.hull_id is not None:
        # Includes GENERIC_FREIGHTER_SENTINEL_HULL_ID (0) on freighter option sets.
        return option_set.hull_id
    return None


def _resolve_component_id(
    *,
    locks_id: int | None,
    option_set_id: int | None,
    record_field: FleetFieldConstraint,
) -> int | None:
    """Locks, then positive option-set id, then positive known field."""
    if locks_id is not None:
        return locks_id
    if option_set_id is not None and option_set_id > 0:
        return option_set_id
    return known_positive_component_id(record_field)


def _resolve_engine(
    record: FleetShipRecord,
    *,
    option_set: FleetBuildOptionSet | None,
    locks_engine_id: int | None,
    engines_by_id: dict[int, Engine],
    default_engine: Engine | None,
) -> Engine | None:
    engine_id = _resolve_component_id(
        locks_id=locks_engine_id,
        option_set_id=option_set.engine_id if option_set is not None else None,
        record_field=record.fields.engine,
    )
    if engine_id is not None:
        engine = engines_by_id.get(engine_id)
        if engine is not None:
            return engine
    return default_engine


def _resolve_weapon_fit[T: Beam | Torpedo](
    *,
    record_field: FleetFieldConstraint,
    option_set_id: int | None,
    option_set_count: int | None,
    locks_id: int | None,
    locks_count: int | None,
    slot_capacity: int,
    components_by_id: dict[int, T],
    default_component: T | None,
) -> tuple[T | None, int | None]:
    """Resolve weapon component and count; unknown slots fill full at default tech.

    Returns ``(component, count)``. Count ``None`` means not estimable (needed a
    part that is missing from the catalog). Count ``0`` is confirmed empty.
    """
    if _is_known_zero_field(record_field) or option_set_count == 0:
        return None, 0

    if slot_capacity <= 0:
        return None, 0

    component_id = _resolve_component_id(
        locks_id=locks_id,
        option_set_id=option_set_id,
        record_field=record_field,
    )

    count = locks_count
    if count is None and option_set_count is not None:
        count = option_set_count
    if count is None:
        # Fog / unknown slot fill -- treat as full at minimal-tech parts.
        count = slot_capacity

    if count <= 0:
        return None, 0

    component: T | None = None
    if component_id is not None:
        component = components_by_id.get(component_id)
    if component is None:
        component = default_component
    if component is None:
        return None, None
    return component, count


def _is_known_zero_field(constraint: FleetFieldConstraint) -> bool:
    return (
        isinstance(constraint, FleetFieldKnown)
        and isinstance(constraint.value, int)
        and constraint.value == 0
    )

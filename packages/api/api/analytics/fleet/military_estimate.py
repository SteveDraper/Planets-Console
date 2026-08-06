"""Wire-only fleet ship military estimates for table/stream records.

Not persisted on the durable ledger. Uses the shared ship-build military helper
and ``default_build_components`` for unknown beam/tube/engine fills.
"""

from __future__ import annotations

from api.analytics.fleet.observation_option_locks import observation_locks_from_record
from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetFieldKnown,
    FleetShipRecord,
)
from api.analytics.military_score_inference.ship_build_combos import GENERIC_FREIGHTER_COMBO_ID
from api.analytics.military_score_inference.ship_build_scoring import (
    default_build_components,
    ship_build_military_score_delta_2x,
)
from api.concepts.hulls import is_generic_freighter_sentinel_hull_id
from api.concepts.turn_component_catalog import (
    beams_by_id,
    engines_by_id,
    hulls_by_id,
    torpedos_by_id,
)
from api.models.components import Beam, Engine, Torpedo
from api.models.game import TurnInfo


def resolve_display_default_build_option_set(
    record: FleetShipRecord,
) -> FleetBuildOptionSet | None:
    """Display-default option set: explicit index, else highest solution rank weight."""
    option_sets = record.build_option_sets
    if not option_sets:
        return None
    index = record.display_default_option_set_index
    if index is not None and 0 <= index < len(option_sets):
        return option_sets[index]
    best_index = 0
    best_weight = option_sets[0].solution_rank_weight
    for candidate_index, option_set in enumerate(option_sets[1:], start=1):
        if option_set.solution_rank_weight > best_weight:
            best_weight = option_set.solution_rank_weight
            best_index = candidate_index
    return option_sets[best_index]


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

    hull_id = locks.hull_id
    if hull_id is None and option_set is not None and option_set.hull_id is not None:
        hull_id = option_set.hull_id
    if (
        hull_id is None
        and option_set is not None
        and option_set.combo_id == GENERIC_FREIGHTER_COMBO_ID
    ):
        hull_id = 0

    if hull_id is None:
        return None
    if is_generic_freighter_sentinel_hull_id(hull_id):
        return 0

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

    return ship_build_military_score_delta_2x(
        hull,
        engine,
        beam,
        torpedo,
        beam_count=beam_count,
        launcher_count=launcher_count,
    )


def _resolve_engine(
    record: FleetShipRecord,
    *,
    option_set: FleetBuildOptionSet | None,
    locks_engine_id: int | None,
    engines_by_id: dict[int, Engine],
    default_engine: Engine | None,
) -> Engine | None:
    engine_id = locks_engine_id
    if engine_id is None and option_set is not None and option_set.engine_id is not None:
        if option_set.engine_id > 0:
            engine_id = option_set.engine_id
    if engine_id is None and isinstance(record.fields.engine, FleetFieldKnown):
        value = record.fields.engine.value
        if isinstance(value, int) and value > 0:
            engine_id = value
    if engine_id is not None:
        engine = engines_by_id.get(engine_id)
        if engine is not None:
            return engine
    return default_engine


def _resolve_weapon_fit[T: Beam | Torpedo](
    *,
    record_field: object,
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

    component_id = locks_id
    if component_id is None and option_set_id is not None and option_set_id > 0:
        component_id = option_set_id
    if component_id is None and isinstance(record_field, FleetFieldKnown):
        value = record_field.value
        if isinstance(value, int) and value > 0:
            component_id = value

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


def _is_known_zero_field(constraint: object) -> bool:
    return (
        isinstance(constraint, FleetFieldKnown)
        and isinstance(constraint.value, int)
        and constraint.value == 0
    )

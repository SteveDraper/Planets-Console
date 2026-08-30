"""Prior-fleet decrease candidates for ship loss / gift / trade departures.

Active fleet ship records on the prior-turn acquisition ledger. Hull-known or
option-set-bounded records contribute that military; unknown-hull inferred
records contribute only that record's envelope. The race build catalog is not
a source of departing hulls.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.fleet.ship_class import record_ship_class
from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetFieldKnown,
    FleetShipClass,
    FleetShipRecord,
)
from api.concepts.hulls import (
    is_generic_freighter_sentinel_hull_id,
    is_unknown_military_ship_sentinel_hull_id,
)
from api.concepts.ship_build_military import (
    ship_build_military_score_delta_2x,
    warship_construction_envelope_2x,
)
from api.models.components import Beam, Engine, Hull, Torpedo


@dataclass(frozen=True)
class PriorFleetDecreaseCandidate:
    record_id: str
    ship_class: FleetShipClass
    score_delta_2x_min: int
    score_delta_2x_max: int

    @property
    def is_point_military(self) -> bool:
        return self.score_delta_2x_min == self.score_delta_2x_max


def prior_fleet_decrease_candidates(
    records: tuple[FleetShipRecord, ...],
    *,
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
    buildable_hull_ids: frozenset[int],
) -> tuple[PriorFleetDecreaseCandidate, ...]:
    """Active prior-turn records that may leave the roster this host turn."""
    race_envelope = warship_construction_envelope_2x(
        hulls_by_id=hulls_by_id,
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
        buildable_hull_ids=buildable_hull_ids,
    )
    candidates: list[PriorFleetDecreaseCandidate] = []
    for record in records:
        if record.disposition != "active":
            continue
        ship_class = record_ship_class(record, hulls_by_id)
        if ship_class is None:
            continue
        military = _departure_military_2x(
            record,
            ship_class=ship_class,
            hulls_by_id=hulls_by_id,
            engines_by_id=engines_by_id,
            beams_by_id=beams_by_id,
            torpedos_by_id=torpedos_by_id,
            race_envelope=race_envelope,
        )
        if military is None:
            continue
        min_2x, max_2x = military
        candidates.append(
            PriorFleetDecreaseCandidate(
                record_id=record.record_id,
                ship_class=ship_class,
                score_delta_2x_min=min_2x,
                score_delta_2x_max=max_2x,
            )
        )
    return tuple(candidates)


def decrease_capacity_by_class(
    candidates: tuple[PriorFleetDecreaseCandidate, ...],
) -> tuple[int, int]:
    """Return (warship_count, freighter_count) of decrease candidates."""
    warships = sum(1 for candidate in candidates if candidate.ship_class == "warship")
    freighters = sum(1 for candidate in candidates if candidate.ship_class == "freighter")
    return warships, freighters


def _departure_military_2x(
    record: FleetShipRecord,
    *,
    ship_class: FleetShipClass,
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
    race_envelope: tuple[int, int] | None,
) -> tuple[int, int] | None:
    option_envelope = _option_set_envelope_2x(record.build_option_sets)
    point = _known_fill_military_2x(
        record,
        hulls_by_id=hulls_by_id,
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
    )
    if point is not None:
        return point, point
    if option_envelope is not None:
        return option_envelope
    if ship_class == "freighter":
        return 0, 0
    if race_envelope is None:
        return None
    return race_envelope


def _option_set_envelope_2x(
    option_sets: list[FleetBuildOptionSet],
) -> tuple[int, int] | None:
    mins: list[int] = []
    maxes: list[int] = []
    for option_set in option_sets:
        if option_set.military_score_delta_2x_min is None:
            continue
        if option_set.military_score_delta_2x_max is None:
            continue
        mins.append(option_set.military_score_delta_2x_min)
        maxes.append(option_set.military_score_delta_2x_max)
    if not mins:
        return None
    return min(mins), max(maxes)


def _known_fill_military_2x(
    record: FleetShipRecord,
    *,
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
) -> int | None:
    hull_id = _known_positive_id(record.fields.hull)
    if hull_id is None:
        hull_id = _unique_option_hull_id(record.build_option_sets)
    if hull_id is None:
        return None
    if is_generic_freighter_sentinel_hull_id(hull_id):
        return 0
    if is_unknown_military_ship_sentinel_hull_id(hull_id):
        return None
    hull = hulls_by_id.get(hull_id)
    if hull is None:
        return None
    option_set = _unique_bounded_option_set(record.build_option_sets, hull_id=hull_id)
    engine_id = _known_positive_id(record.fields.engine)
    beam_id = _known_non_negative_id(record.fields.beams)
    torp_id = _known_non_negative_id(record.fields.launchers)
    beam_count = None
    launcher_count = None
    if option_set is not None:
        if engine_id is None:
            engine_id = option_set.engine_id
        if beam_id is None:
            beam_id = option_set.beam_id
        if torp_id is None:
            torp_id = option_set.torp_id
        beam_count = option_set.beam_count
        launcher_count = option_set.launcher_count
    if engine_id is None or engine_id not in engines_by_id:
        return None
    if beam_count is None or launcher_count is None:
        return None
    beam = beams_by_id.get(beam_id) if beam_id else None
    torpedo = torpedos_by_id.get(torp_id) if torp_id else None
    return ship_build_military_score_delta_2x(
        hull,
        engines_by_id[engine_id],
        beam,
        torpedo,
        beam_count=beam_count,
        launcher_count=launcher_count,
    )


def _known_positive_id(constraint: object) -> int | None:
    if not isinstance(constraint, FleetFieldKnown):
        return None
    value = constraint.value
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    return value


def _known_non_negative_id(constraint: object) -> int | None:
    if not isinstance(constraint, FleetFieldKnown):
        return None
    value = constraint.value
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _unique_option_hull_id(option_sets: list[FleetBuildOptionSet]) -> int | None:
    hull_ids = {option_set.hull_id for option_set in option_sets if option_set.hull_id is not None}
    if len(hull_ids) != 1:
        return None
    return next(iter(hull_ids))


def _unique_bounded_option_set(
    option_sets: list[FleetBuildOptionSet],
    *,
    hull_id: int,
) -> FleetBuildOptionSet | None:
    matching = [option_set for option_set in option_sets if option_set.hull_id == hull_id]
    if len(matching) != 1:
        return None
    return matching[0]

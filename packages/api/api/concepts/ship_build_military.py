"""Host-aligned ship-build military score helpers.

Shared by fleet wire estimates and military-score inference. Construction value
follows AutoScore (megacredits + 5 * minerals); military deltas are scaled 2x.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.concepts.hulls import hull_has_weapon_slots
from api.models.components import Beam, Engine, Hull, Torpedo


def construction_value(megacredits: int, minerals: int) -> int:
    """AutoScore-style construction value: megacredits plus five times minerals."""
    return megacredits + 5 * minerals


def ship_construction_score_delta_2x(
    construction_megacredits: int,
    construction_minerals: int,
) -> int:
    """Scaled military-score delta for one ship hull plus fitted components."""
    return 2 * construction_value(construction_megacredits, construction_minerals)


@dataclass(frozen=True)
class DefaultBuildComponents:
    engine: Engine | None
    beam: Beam | None
    torpedo: Torpedo | None


def is_military_hull(hull: Hull) -> bool:
    return hull_has_weapon_slots(hull)


def ship_build_counts_as_warship(
    hull: Hull,
    *,
    beam_count: int,
    launcher_count: int,
) -> bool:
    """Whether a build counts toward ``shipchange`` rather than ``freighterchange``.

    Hulls with fighter bays always count as warships. Other military hulls count as
    freighters on the scoreboard when built without beams or launchers fitted.
    """
    if hull.fighterbays > 0:
        return True
    return beam_count > 0 or launcher_count > 0


def default_build_components(
    *,
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
    default_engine_id: int | None = None,
) -> DefaultBuildComponents:
    if default_engine_id is None:
        resolved_engine_id = min(engines_by_id) if engines_by_id else None
    else:
        resolved_engine_id = default_engine_id
    engine = engines_by_id.get(resolved_engine_id) if resolved_engine_id is not None else None
    default_beam = min(beams_by_id.values(), key=lambda beam: beam.id) if beams_by_id else None
    default_torpedo = (
        min(torpedos_by_id.values(), key=lambda torpedo: torpedo.techlevel)
        if torpedos_by_id
        else None
    )
    return DefaultBuildComponents(engine=engine, beam=default_beam, torpedo=default_torpedo)


def ship_build_score_delta_2x(
    hull: Hull,
    engine: Engine,
    beam: Beam | None,
    torpedo: Torpedo | None,
    *,
    beam_count: int,
    launcher_count: int,
) -> int:
    """Hull construction score only; ammo is modeled by separate catalog actions."""
    engine_count = hull.engines
    construction_megacredits = hull.cost + engine.cost * engine_count
    construction_minerals = _component_minerals(hull) + _component_minerals(engine) * engine_count

    if beam is not None and beam_count > 0:
        construction_megacredits += beam.cost * beam_count
        construction_minerals += _component_minerals(beam) * beam_count

    if torpedo is not None and launcher_count > 0:
        construction_megacredits += torpedo.launchercost * launcher_count
        construction_minerals += _component_minerals(torpedo) * launcher_count

    return ship_construction_score_delta_2x(
        construction_megacredits,
        construction_minerals,
    )


def ship_build_has_zero_military_score(
    hull: Hull,
    *,
    beam_count: int,
    launcher_count: int,
) -> bool:
    """True when military score is zero regardless of which engine is fitted."""
    if not is_military_hull(hull):
        return True
    return beam_count == 0 and launcher_count == 0 and hull.fighterbays == 0


def ship_build_military_score_delta_2x(
    hull: Hull,
    engine: Engine,
    beam: Beam | None,
    torpedo: Torpedo | None,
    *,
    beam_count: int,
    launcher_count: int,
) -> int:
    """Military-score contribution for a ship build.

    Freighters and unarmed military hulls without fighter bays contribute zero.
    Carriers and other fighter-bay hulls score hull construction even when empty.
    Loaded fighters are modeled by separate aggregate actions, not ship combos.
    """
    if ship_build_has_zero_military_score(
        hull,
        beam_count=beam_count,
        launcher_count=launcher_count,
    ):
        return 0
    return ship_build_score_delta_2x(
        hull,
        engine,
        beam,
        torpedo,
        beam_count=beam_count,
        launcher_count=launcher_count,
    )


def warship_construction_envelope_2x(
    *,
    hulls_by_id: dict[int, Hull],
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
    buildable_hull_ids: frozenset[int],
) -> tuple[int, int] | None:
    """Per-unit military 2x range over legal warship fills for buildable hulls.

    Min is the cheapest fill that still counts as a warship (one cheapest beam or
    launcher, or zero weapons on a fighter-bay hull). Max is the most expensive
    fill (costliest engines in every slot, weapons at hull max). Engines always
    fill every slot. Returns None when no legal warship fill exists.
    """
    scores: list[int] = []
    for hull_id in buildable_hull_ids:
        hull = hulls_by_id.get(hull_id)
        if hull is None or not is_military_hull(hull):
            continue
        hull_scores = _legal_warship_fill_scores_2x(
            hull,
            engines_by_id=engines_by_id,
            beams_by_id=beams_by_id,
            torpedos_by_id=torpedos_by_id,
        )
        scores.extend(hull_scores)
    if not scores:
        return None
    return min(scores), max(scores)


def _legal_warship_fill_scores_2x(
    hull: Hull,
    *,
    engines_by_id: dict[int, Engine],
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
) -> list[int]:
    if hull.engines > 0 and not engines_by_id:
        return []
    engine_min, engine_max = _minmax_engines(engines_by_id)
    if engine_min is None or engine_max is None:
        return []

    min_weapon_fills = _min_warship_weapon_fills(
        hull, beams_by_id=beams_by_id, torpedos_by_id=torpedos_by_id
    )
    max_weapon_fill = _max_warship_weapon_fill(
        hull, beams_by_id=beams_by_id, torpedos_by_id=torpedos_by_id
    )
    scores: list[int] = []
    for beam, torpedo, beam_count, launcher_count in min_weapon_fills:
        scores.append(
            ship_build_military_score_delta_2x(
                hull,
                engine_min,
                beam,
                torpedo,
                beam_count=beam_count,
                launcher_count=launcher_count,
            )
        )
    if max_weapon_fill is not None:
        beam, torpedo, beam_count, launcher_count = max_weapon_fill
        scores.append(
            ship_build_military_score_delta_2x(
                hull,
                engine_max,
                beam,
                torpedo,
                beam_count=beam_count,
                launcher_count=launcher_count,
            )
        )
    return scores


def _minmax_engines(
    engines_by_id: dict[int, Engine],
) -> tuple[Engine | None, Engine | None]:
    if not engines_by_id:
        return None, None
    engines = list(engines_by_id.values())
    cheapest = min(engines, key=_engine_construction_key)
    costliest = max(engines, key=_engine_construction_key)
    return cheapest, costliest


def _engine_construction_key(engine: Engine) -> tuple[int, int]:
    return (construction_value(engine.cost, _component_minerals(engine)), engine.id)


def _beam_construction_key(beam: Beam) -> tuple[int, int]:
    return (construction_value(beam.cost, _component_minerals(beam)), beam.id)


def _torpedo_launcher_construction_key(torpedo: Torpedo) -> tuple[int, int]:
    return (
        construction_value(torpedo.launchercost, _component_minerals(torpedo)),
        torpedo.id,
    )


def _min_warship_weapon_fills(
    hull: Hull,
    *,
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
) -> list[tuple[Beam | None, Torpedo | None, int, int]]:
    """Legal minimum weapon fills that still count as a warship."""
    if hull.fighterbays > 0:
        return [(None, None, 0, 0)]
    fills: list[tuple[Beam | None, Torpedo | None, int, int]] = []
    if hull.beams > 0 and beams_by_id:
        cheapest_beam = min(beams_by_id.values(), key=_beam_construction_key)
        fills.append((cheapest_beam, None, 1, 0))
    if hull.launchers > 0 and torpedos_by_id:
        cheapest_torp = min(torpedos_by_id.values(), key=_torpedo_launcher_construction_key)
        fills.append((None, cheapest_torp, 0, 1))
    return fills


def _max_warship_weapon_fill(
    hull: Hull,
    *,
    beams_by_id: dict[int, Beam],
    torpedos_by_id: dict[int, Torpedo],
) -> tuple[Beam | None, Torpedo | None, int, int] | None:
    beam: Beam | None = None
    torpedo: Torpedo | None = None
    beam_count = 0
    launcher_count = 0
    if hull.beams > 0 and beams_by_id:
        beam = max(beams_by_id.values(), key=_beam_construction_key)
        beam_count = hull.beams
    if hull.launchers > 0 and torpedos_by_id:
        torpedo = max(torpedos_by_id.values(), key=_torpedo_launcher_construction_key)
        launcher_count = hull.launchers
    if not ship_build_counts_as_warship(hull, beam_count=beam_count, launcher_count=launcher_count):
        return None
    return beam, torpedo, beam_count, launcher_count


def _component_minerals(component: Hull | Engine | Beam | Torpedo) -> int:
    return component.tritanium + component.duranium + component.molybdenum

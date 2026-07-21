"""Ship hull classification and construction score helpers for build inference."""

from dataclasses import dataclass

from api.analytics.military_score_inference.scoring import ship_construction_score_delta_2x
from api.models.components import Beam, Engine, Hull, Torpedo


@dataclass(frozen=True)
class DefaultBuildComponents:
    engine: Engine | None
    beam: Beam | None
    torpedo: Torpedo | None


def is_military_hull(hull: Hull) -> bool:
    from api.concepts.hulls import hull_has_weapon_slots

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


def _component_minerals(component: Hull | Engine | Beam | Torpedo) -> int:
    return component.tritanium + component.duranium + component.molybdenum

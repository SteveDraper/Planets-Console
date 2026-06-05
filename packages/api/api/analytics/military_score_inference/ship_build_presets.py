"""Ship-build preset identifiers, matching, and construction score helpers."""

from dataclasses import dataclass

from api.analytics.military_score_inference.scoring import ship_construction_score_delta_2x
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo
from api.models.ship import Ship

LOADOUT_PRESET_EMPTY = "empty"
LOADOUT_PRESET_TORPEDOES = "torpedoes"


@dataclass(frozen=True)
class DefaultBuildComponents:
    engine: Engine | None
    beam: Beam | None
    torpedo: Torpedo | None


def is_military_hull(hull: Hull) -> bool:
    return hull.beams > 0 or hull.launchers > 0 or hull.fighterbays > 0


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


def default_build_components_from_turn(turn: TurnInfo) -> DefaultBuildComponents:
    return default_build_components(
        engines_by_id={engine.id: engine for engine in turn.engines},
        beams_by_id={beam.id: beam for beam in turn.beams},
        torpedos_by_id={torpedo.id: torpedo for torpedo in turn.torpedos},
    )


def torpedo_preset_catalog_eligible(hull: Hull, default_torpedo: Torpedo | None) -> bool:
    return hull.launchers > 0 and default_torpedo is not None


def matches_torpedo_preset(ship: Ship, hull: Hull) -> bool:
    if hull.beams > 0 and ship.beams != hull.beams:
        return False
    if hull.launchers > 0 and ship.torpedoid == 0:
        return False
    return hull.launchers > 0


def matches_empty_preset(ship: Ship, hull: Hull) -> bool:
    if hull.beams == 0 and hull.launchers == 0:
        return True
    if hull.beams > 0 and ship.beams != 0:
        return False
    if hull.launchers > 0 and ship.torpedoid != 0:
        return False
    return True


def build_action_id(hull_id: int, preset_id: str) -> str:
    return f"build_{hull_id}_{preset_id}"


def ship_to_build_action_id(
    ship: Ship,
    hull: Hull,
    *,
    default_torpedo: Torpedo | None,
) -> str | None:
    if not is_military_hull(hull):
        return build_action_id(hull.id, LOADOUT_PRESET_EMPTY)

    if torpedo_preset_catalog_eligible(hull, default_torpedo) and matches_torpedo_preset(
        ship, hull
    ):
        return build_action_id(hull.id, LOADOUT_PRESET_TORPEDOES)

    if matches_empty_preset(ship, hull):
        return build_action_id(hull.id, LOADOUT_PRESET_EMPTY)

    return None


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


def ship_build_score_delta_2x_for_action_id(action_id: str, turn: TurnInfo) -> int:
    hull_id_str, preset = action_id.removeprefix("build_").rsplit("_", 1)
    hull_id = int(hull_id_str)
    hull = next(h for h in turn.hulls if h.id == hull_id)
    defaults = default_build_components_from_turn(turn)
    if defaults.engine is None:
        return 0
    armed = preset == LOADOUT_PRESET_TORPEDOES
    return ship_build_score_delta_2x(
        hull,
        defaults.engine,
        defaults.beam,
        defaults.torpedo,
        beam_count=hull.beams if armed else 0,
        launcher_count=hull.launchers if armed else 0,
    )


def _component_minerals(component: Hull | Engine | Beam | Torpedo) -> int:
    return component.tritanium + component.duranium + component.molybdenum

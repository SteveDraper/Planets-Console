"""Inventory delta helpers for inference corpus ground truth and complexity."""

from collections import Counter

from api.analytics.military_score_inference.ship_build_combos import ship_build_combo_id
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo
from api.models.ship import Ship


def hulls_by_id(turn: TurnInfo) -> dict[int, Hull]:
    return {hull.id: hull for hull in turn.hulls}


def engines_by_id(turn: TurnInfo) -> dict[int, Engine]:
    return {engine.id: engine for engine in turn.engines}


def beams_by_id(turn: TurnInfo) -> dict[int, Beam]:
    return {beam.id: beam for beam in turn.beams}


def torpedos_by_id(turn: TurnInfo) -> dict[int, Torpedo]:
    return {torp.id: torp for torp in turn.torpedos}


def owned_active_ships(turn: TurnInfo, player_id: int) -> list[Ship]:
    return [ship for ship in turn.ships if ship.ownerid == player_id and ship.turnkilled == 0]


def new_owned_ships(prior_turn: TurnInfo, score_turn: TurnInfo, player_id: int) -> list[Ship]:
    prior_ids = {ship.id for ship in owned_active_ships(prior_turn, player_id)}
    return [ship for ship in owned_active_ships(score_turn, player_id) if ship.id not in prior_ids]


def new_ship_load_action_counts(new_ships: list[Ship], score_turn: TurnInfo) -> Counter[str]:
    """Return load action counts attributable to newly built ships.

    Returns empty: turn snapshots reflect post-order ship state while scoreboard
    military deltas reflect pre-order totals. Fighters and torpedoes visible on a
    new ship at turn end are often loaded via client-side build/transfer actions that
    are not reflected in ``militarychange`` for that row.
    """
    del new_ships, score_turn
    return Counter()


def is_fighter_capable(ship: Ship, hull: Hull) -> bool:
    return hull.fighterbays > 0 or ship.bays > 0


def is_torp_capable(ship: Ship, hull: Hull) -> bool:
    return hull.launchers > 0 or ship.torps > 0


def loaded_fighter_count(ship: Ship, hull: Hull) -> int:
    """``Ship.ammo`` counts fighters only on fighter-capable hulls."""
    return ship.ammo if is_fighter_capable(ship, hull) else 0


def loaded_torpedo_count(ship: Ship, hull: Hull) -> int:
    """``Ship.ammo`` counts loaded torpedoes on torp-capable hulls without fighter bays."""
    if is_fighter_capable(ship, hull):
        return 0
    return ship.ammo if is_torp_capable(ship, hull) else 0


def ship_to_build_combo_id(ship: Ship, turn: TurnInfo) -> str | None:
    """Map a ship's fitted components to the inference catalog combo id scheme."""
    hull = hulls_by_id(turn).get(ship.hullid)
    if hull is None:
        return None
    beam_id = ship.beamid if ship.beams > 0 else None
    torp_id = ship.torpedoid if ship.torps > 0 else None
    return ship_build_combo_id(
        hull_id=ship.hullid,
        engine_id=ship.engineid,
        beam_id=beam_id,
        torp_id=torp_id,
        beam_count=ship.beams,
        launcher_count=ship.torps,
    )


def describe_new_ship_build(ship: Ship, turn: TurnInfo) -> str:
    """Human-readable build line with engines, beams, launchers, and build-time loadout."""
    hull_map = hulls_by_id(turn)
    engine_map = engines_by_id(turn)
    beam_map = beams_by_id(turn)
    torp_map = torpedos_by_id(turn)

    hull = hull_map.get(ship.hullid)
    hull_name = hull.name if hull is not None else f"hull {ship.hullid}"
    if hull is None:
        return f"built 1x {hull_name}"

    components: list[str] = []
    engine = engine_map.get(ship.engineid)
    if engine is not None and hull.engines > 0:
        components.append(f"{hull.engines}x {engine.name}")

    if ship.beams > 0:
        beam = beam_map.get(ship.beamid)
        beam_label = beam.name if beam is not None else f"beam {ship.beamid}"
        components.append(f"{ship.beams}x {beam_label}")

    if ship.torps > 0:
        torp = torp_map.get(ship.torpedoid)
        torp_label = torp.name if torp is not None else f"torp {ship.torpedoid}"
        components.append(f"{ship.torps}x {torp_label} launcher{'s' if ship.torps != 1 else ''}")

    line = f"built 1x {hull_name}"
    if components:
        line += f": {', '.join(components)}"

    fighters = loaded_fighter_count(ship, hull)
    if fighters > 0:
        line += f", loaded {fighters} fighter{'s' if fighters != 1 else ''}"

    loaded_torps = loaded_torpedo_count(ship, hull)
    if loaded_torps > 0:
        torp = torp_map.get(ship.torpedoid)
        torp_label = torp.name if torp is not None else f"torp type {ship.torpedoid}"
        line += f", loaded {loaded_torps}x {torp_label}"

    return line


def total_loaded_fighters(turn: TurnInfo, player_id: int) -> int:
    hull_map = hulls_by_id(turn)
    return sum(
        loaded_fighter_count(ship, hull_map[ship.hullid])
        for ship in owned_active_ships(turn, player_id)
        if ship.hullid in hull_map
    )


def loaded_torpedo_counts_by_type(turn: TurnInfo, player_id: int) -> dict[int, int]:
    hull_map = hulls_by_id(turn)
    counts: dict[int, int] = {}
    for ship in owned_active_ships(turn, player_id):
        hull = hull_map.get(ship.hullid)
        if hull is None:
            continue
        loaded = loaded_torpedo_count(ship, hull)
        if loaded > 0 and ship.torpedoid:
            counts[ship.torpedoid] = counts.get(ship.torpedoid, 0) + loaded
    return counts


def fighter_load_delta(
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
    *,
    exclude_ship_ids: frozenset[int] = frozenset(),
) -> int:
    def count(turn: TurnInfo) -> int:
        return sum(
            loaded_fighter_count(ship, hulls_by_id(turn)[ship.hullid])
            for ship in owned_active_ships(turn, player_id)
            if ship.id not in exclude_ship_ids and ship.hullid in hulls_by_id(turn)
        )

    return max(0, count(score_turn) - count(prior_turn))


def torpedo_load_delta_by_type(
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
    *,
    exclude_ship_ids: frozenset[int] = frozenset(),
) -> dict[int, int]:
    prior_counts = _loaded_torpedo_counts_excluding(prior_turn, player_id, exclude_ship_ids)
    score_counts = _loaded_torpedo_counts_excluding(score_turn, player_id, exclude_ship_ids)
    deltas: dict[int, int] = {}
    for torp_id in set(prior_counts) | set(score_counts):
        delta = score_counts.get(torp_id, 0) - prior_counts.get(torp_id, 0)
        if delta > 0:
            deltas[torp_id] = delta
    return deltas


def _loaded_torpedo_counts_excluding(
    turn: TurnInfo,
    player_id: int,
    exclude_ship_ids: frozenset[int],
) -> dict[int, int]:
    hull_map = hulls_by_id(turn)
    counts: dict[int, int] = {}
    for ship in owned_active_ships(turn, player_id):
        if ship.id in exclude_ship_ids or ship.hullid not in hull_map:
            continue
        loaded = loaded_torpedo_count(ship, hull_map[ship.hullid])
        if loaded > 0 and ship.torpedoid:
            counts[ship.torpedoid] = counts.get(ship.torpedoid, 0) + loaded
    return counts


def planet_counts_by_owner(turn: TurnInfo) -> dict[int, int]:
    counts: dict[int, int] = {}
    for planet in turn.planets:
        counts[planet.ownerid] = counts.get(planet.ownerid, 0) + 1
    return counts


def starbase_planet_ids(turn: TurnInfo) -> set[int]:
    return {starbase.planetid for starbase in turn.starbases}


def starbase_counts_by_owner(turn: TurnInfo) -> dict[int, int]:
    starbase_planets = starbase_planet_ids(turn)
    counts: dict[int, int] = {}
    for planet in turn.planets:
        if planet.id in starbase_planets:
            counts[planet.ownerid] = counts.get(planet.ownerid, 0) + 1
    return counts


def starbase_fighters_by_planet(turn: TurnInfo) -> dict[int, int]:
    return {starbase.planetid: starbase.fighters for starbase in turn.starbases}


def starbase_defense_by_planet(turn: TurnInfo) -> dict[int, int]:
    return {starbase.planetid: starbase.defense for starbase in turn.starbases}


def starbase_fighters_for_owner(turn: TurnInfo, player_id: int) -> int:
    fighters_by_planet = starbase_fighters_by_planet(turn)
    return sum(
        fighters_by_planet.get(planet.id, 0)
        for planet in turn.planets
        if planet.ownerid == player_id
    )


def starbase_defense_for_owner(turn: TurnInfo, player_id: int) -> int:
    defense_by_planet = starbase_defense_by_planet(turn)
    return sum(
        defense_by_planet.get(planet.id, 0)
        for planet in turn.planets
        if planet.ownerid == player_id
    )


def planet_defense_for_owner(turn: TurnInfo, player_id: int) -> int:
    return sum(planet.defense for planet in turn.planets if planet.ownerid == player_id)


def _positive_inventory_delta(prior_value: int, score_value: int) -> int:
    return max(0, score_value - prior_value)


def starbase_fighter_inventory_delta(
    prior_turn: TurnInfo, score_turn: TurnInfo, player_id: int
) -> int:
    return _positive_inventory_delta(
        starbase_fighters_for_owner(prior_turn, player_id),
        starbase_fighters_for_owner(score_turn, player_id),
    )


def starbase_defense_inventory_delta(
    prior_turn: TurnInfo, score_turn: TurnInfo, player_id: int
) -> int:
    return _positive_inventory_delta(
        starbase_defense_for_owner(prior_turn, player_id),
        starbase_defense_for_owner(score_turn, player_id),
    )


def planet_defense_inventory_delta(
    prior_turn: TurnInfo, score_turn: TurnInfo, player_id: int
) -> int:
    return _positive_inventory_delta(
        planet_defense_for_owner(prior_turn, player_id),
        planet_defense_for_owner(score_turn, player_id),
    )

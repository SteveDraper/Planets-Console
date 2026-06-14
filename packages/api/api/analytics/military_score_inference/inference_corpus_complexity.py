"""Complexity classification for inference corpus cases and prior mining."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from api.analytics.military_score_inference.ship_inventory import (
    fighter_load_delta,
    new_owned_ships,
    owned_active_ships,
    planet_counts_by_owner,
    planet_defense_inventory_delta,
    starbase_counts_by_owner,
    starbase_defense_inventory_delta,
    starbase_fighter_inventory_delta,
    torpedo_load_delta_by_type,
)
from api.models.game import TurnInfo
from api.models.player import Score
from api.models.ship import Ship

ComplexityLevel = Literal["minimal", "routine", "heavy", "adjunct"]
COMPLEXITY_ORDINAL: dict[ComplexityLevel, int] = {
    "minimal": 0,
    "routine": 1,
    "heavy": 2,
    "adjunct": 3,
}

MILITARY_CHANGE_UNEXPLAINED_THRESHOLD = 500
HEAVY_NEW_SHIP_COUNT = 3
HEAVY_CONSTRUCTION_MC = 2000
HEAVY_AGGREGATE_LOAD_UNITS = 51
ROUTINE_NEW_SHIP_COUNT = 2
ROUTINE_AGGREGATE_LOAD_MIN = 11
ROUTINE_AGGREGATE_LOAD_MAX = 50


@dataclass(frozen=True)
class MergedTurnInventory:
    """Ship and planet snapshots merged across perspectives for adjunct detection."""

    prior_ships: tuple[Ship, ...]
    score_ships: tuple[Ship, ...]
    prior_planet_count_by_owner: dict[int, int]
    score_planet_count_by_owner: dict[int, int]
    prior_starbase_count_by_owner: dict[int, int]
    score_starbase_count_by_owner: dict[int, int]


def parse_max_complexity(value: str) -> ComplexityLevel:
    """Parse CLI ``--max-complexity`` as a level name or ordinal 0-3."""
    normalized = value.strip().lower()
    if normalized.isdigit():
        ordinal = int(normalized)
        for level, level_ordinal in COMPLEXITY_ORDINAL.items():
            if level_ordinal == ordinal:
                return level
        raise ValueError(f"invalid max complexity ordinal {ordinal}; expected 0-3")
    if normalized in COMPLEXITY_ORDINAL:
        return normalized
    raise ValueError(
        f"invalid max complexity {value!r}; expected minimal, routine, heavy, adjunct, or 0-3"
    )


def classify_complexity(
    *,
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
    score: Score,
    merged: MergedTurnInventory,
) -> tuple[ComplexityLevel, tuple[str, ...]]:
    """Return the highest complexity level and human-readable reason strings."""
    reasons: list[str] = []

    new_ships = new_owned_ships(prior_turn, score_turn, player_id)
    new_ship_count = len(new_ships)
    aggregate_load_units, aggregate_families = _aggregate_load_signals(
        prior_turn, score_turn, player_id
    )

    if _has_ship_count_decrease(prior_turn, score_turn, player_id):
        reasons.append("net_ship_count_decrease")
    if _has_base_or_planet_count_decrease(merged, player_id):
        reasons.append("planet_or_starbase_count_decrease")
    if _has_trade_capture_hint(merged, player_id, new_ships):
        reasons.append("trade_or_capture_hint")
    unexplained = _unexplained_military_change(
        score=score,
        new_ships=new_ships,
        score_turn=score_turn,
        aggregate_load_units=aggregate_load_units,
    )
    if unexplained:
        reasons.append(unexplained)

    if reasons:
        return "adjunct", tuple(reasons)

    construction_mc = _new_ship_construction_mc(new_ships, score_turn)
    if (
        new_ship_count >= HEAVY_NEW_SHIP_COUNT
        or construction_mc > HEAVY_CONSTRUCTION_MC
        or aggregate_load_units >= HEAVY_AGGREGATE_LOAD_UNITS
    ):
        heavy_reasons: list[str] = []
        if new_ship_count >= HEAVY_NEW_SHIP_COUNT:
            heavy_reasons.append(f"new_ships={new_ship_count}")
        if construction_mc > HEAVY_CONSTRUCTION_MC:
            heavy_reasons.append(f"construction_mc={construction_mc}")
        if aggregate_load_units >= HEAVY_AGGREGATE_LOAD_UNITS:
            heavy_reasons.append(f"aggregate_load_units={aggregate_load_units}")
        return "heavy", tuple(heavy_reasons)

    if (
        new_ship_count == ROUTINE_NEW_SHIP_COUNT
        or ROUTINE_AGGREGATE_LOAD_MIN <= aggregate_load_units <= ROUTINE_AGGREGATE_LOAD_MAX
        or len(aggregate_families) >= 2
    ):
        routine_reasons: list[str] = []
        if new_ship_count == ROUTINE_NEW_SHIP_COUNT:
            routine_reasons.append(f"new_ships={new_ship_count}")
        if ROUTINE_AGGREGATE_LOAD_MIN <= aggregate_load_units <= ROUTINE_AGGREGATE_LOAD_MAX:
            routine_reasons.append(f"aggregate_load_units={aggregate_load_units}")
        if len(aggregate_families) >= 2:
            routine_reasons.append(f"aggregate_families={','.join(sorted(aggregate_families))}")
        return "routine", tuple(routine_reasons)

    return "minimal", ("small_inventory_delta",)


def merge_turn_inventories(
    *,
    case_perspective_prior: TurnInfo,
    case_perspective_score: TurnInfo,
    other_prior_turns: tuple[TurnInfo, ...],
    other_score_turns: tuple[TurnInfo, ...],
) -> MergedTurnInventory:
    """Merge case perspective with other stored perspectives for adjunct checks."""
    prior_ships = tuple(case_perspective_prior.ships) + tuple(
        ship for turn in other_prior_turns for ship in turn.ships
    )
    score_ships = tuple(case_perspective_score.ships) + tuple(
        ship for turn in other_score_turns for ship in turn.ships
    )
    return MergedTurnInventory(
        prior_ships=prior_ships,
        score_ships=score_ships,
        prior_planet_count_by_owner=planet_counts_by_owner(case_perspective_prior),
        score_planet_count_by_owner=planet_counts_by_owner(case_perspective_score),
        prior_starbase_count_by_owner=starbase_counts_by_owner(case_perspective_prior),
        score_starbase_count_by_owner=starbase_counts_by_owner(case_perspective_score),
    )


def _has_ship_count_decrease(prior_turn: TurnInfo, score_turn: TurnInfo, player_id: int) -> bool:
    prior_count = len(owned_active_ships(prior_turn, player_id))
    score_count = len(owned_active_ships(score_turn, player_id))
    if score_count < prior_count:
        return True

    prior_ids = {ship.id for ship in prior_turn.ships if ship.ownerid == player_id}
    for ship in score_turn.ships:
        if ship.ownerid != player_id:
            continue
        if ship.turnkilled != 0 and ship.turnkilled > prior_turn.settings.turn:
            return True
        if ship.id in prior_ids and ship.id not in {
            active.id for active in owned_active_ships(score_turn, player_id)
        }:
            return True
    return False


def _has_base_or_planet_count_decrease(merged: MergedTurnInventory, player_id: int) -> bool:
    prior_planets = merged.prior_planet_count_by_owner.get(player_id, 0)
    score_planets = merged.score_planet_count_by_owner.get(player_id, 0)
    if score_planets < prior_planets:
        return True

    prior_bases = merged.prior_starbase_count_by_owner.get(player_id, 0)
    score_bases = merged.score_starbase_count_by_owner.get(player_id, 0)
    return score_bases < prior_bases


def _has_trade_capture_hint(
    merged: MergedTurnInventory,
    player_id: int,
    new_ships: list[Ship],
) -> bool:
    case_prior_ids = {
        ship.id for ship in merged.prior_ships if ship.ownerid == player_id and ship.turnkilled == 0
    }
    for ship in new_ships:
        if ship.id in case_prior_ids:
            continue
        for other in merged.prior_ships:
            if other.ownerid == player_id:
                continue
            if other.hullid == ship.hullid and other.x == ship.x and other.y == ship.y:
                return True
    return False


def _new_ship_construction_mc(new_ships: list[Ship], score_turn: TurnInfo) -> int:
    hull_cost_by_id = {hull.id: hull.cost for hull in score_turn.hulls}
    return sum(hull_cost_by_id.get(ship.hullid, 0) for ship in new_ships)


def _aggregate_load_signals(
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
) -> tuple[int, set[str]]:
    families: set[str] = set()
    units = 0

    ship_fighter_delta = fighter_load_delta(prior_turn, score_turn, player_id)
    if ship_fighter_delta > 0:
        families.add("ship_fighters")
        units += ship_fighter_delta

    ship_torp_delta = sum(torpedo_load_delta_by_type(prior_turn, score_turn, player_id).values())
    if ship_torp_delta > 0:
        families.add("ship_torps")
        units += ship_torp_delta

    starbase_fighter_delta = starbase_fighter_inventory_delta(prior_turn, score_turn, player_id)
    if starbase_fighter_delta > 0:
        families.add("starbase_fighters")
        units += starbase_fighter_delta

    starbase_defense_delta = starbase_defense_inventory_delta(prior_turn, score_turn, player_id)
    if starbase_defense_delta > 0:
        families.add("starbase_defense")
        units += starbase_defense_delta

    planet_defense_delta = planet_defense_inventory_delta(prior_turn, score_turn, player_id)
    if planet_defense_delta > 0:
        families.add("planet_defense")
        units += planet_defense_delta

    if new_owned_ships(prior_turn, score_turn, player_id):
        families.add("ship_build")

    return units, families


def _unexplained_military_change(
    *,
    score: Score,
    new_ships: list[Ship],
    score_turn: TurnInfo,
    aggregate_load_units: int,
) -> str | None:
    if score.militarychange >= 0:
        return None
    explained_mc = _new_ship_construction_mc(new_ships, score_turn) + aggregate_load_units
    delta = abs(score.militarychange)
    if delta - explained_mc > MILITARY_CHANGE_UNEXPLAINED_THRESHOLD:
        return f"unexplained_militarychange={delta - explained_mc}"
    return None

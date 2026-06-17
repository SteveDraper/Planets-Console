"""Observation extraction for inference prior mining."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.military_score_inference.aggregate_action_registry import (
    AGGREGATE_ACTION_SPECS,
    SHIP_TORPS_LOADED_ACTION_PREFIX,
    SHIP_TORPS_LOADED_ANY_PRIOR_KEY,
)
from api.analytics.military_score_inference.hull_category import (
    resolve_inference_hull_category,
)
from api.analytics.military_score_inference.inference_corpus_complexity import (
    MergedTurnInventory,
    merge_turn_inventories,
)
from api.analytics.military_score_inference.inference_target import is_after_ship_limit
from api.analytics.military_score_inference.prior_weights_asset import ShipLimitBand
from api.analytics.military_score_inference.ship_inventory import (
    fighter_load_delta,
    fighter_transfer_counts,
    hulls_by_id,
    owned_active_ships,
    planet_defense_inventory_delta,
    starbase_defense_inventory_delta,
    starbase_fighter_inventory_delta,
    torpedo_load_delta_for_type,
)
from api.models.game import TurnInfo
from api.models.player import Score
from api.models.ship import Ship
from api.models.starbase import Starbase

from .turn_cache import MiningTurnCache


@dataclass(frozen=True)
class ShipBuildObservation:
    hull_id: int
    engine_id: int
    beam_id: int
    torpedo_id: int
    beam_count: int
    launcher_count: int
    hull_category: str
    ship_limit_band: ShipLimitBand
    race_id: int
    hull_beam_slots: int
    hull_launcher_slots: int


@dataclass(frozen=True)
class PlayerHostTurnExtraction:
    ship_builds: tuple[ShipBuildObservation, ...]
    aggregate_deltas: dict[str, int]
    ship_build_validation_drops: int
    ship_limit_band: ShipLimitBand
    is_adjunct: bool


def _extract_player_host_turn(
    *,
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
    score: Score,
    race_id: int,
) -> PlayerHostTurnExtraction:
    ship_limit_band: ShipLimitBand = (
        "after_ship_limit" if is_after_ship_limit(score_turn, score) else "before_ship_limit"
    )
    ship_builds, drops = _extract_validated_ship_builds(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=player_id,
        ship_limit_band=ship_limit_band,
        race_id=race_id,
    )
    validated_ship_ids = frozenset(
        ship.id
        for ship in _validated_new_ships(prior_turn, score_turn, player_id, prior_turn.starbases)
    )
    aggregate_deltas = _aggregate_histogram_deltas(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=player_id,
        exclude_ship_ids=validated_ship_ids,
    )
    return PlayerHostTurnExtraction(
        ship_builds=tuple(ship_builds),
        aggregate_deltas=aggregate_deltas,
        ship_build_validation_drops=drops,
        ship_limit_band=ship_limit_band,
        is_adjunct=False,
    )


def _extract_validated_ship_builds(
    *,
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
    ship_limit_band: ShipLimitBand,
    race_id: int,
) -> tuple[list[ShipBuildObservation], int]:
    planets_by_id = {planet.id: planet for planet in prior_turn.planets}
    prior_ship_ids = {ship.id for ship in owned_active_ships(prior_turn, player_id)}
    observations: list[ShipBuildObservation] = []
    drops = 0

    for starbase in prior_turn.starbases:
        if not starbase.isbuilding:
            continue
        planet = planets_by_id.get(starbase.planetid)
        if planet is None or planet.ownerid != player_id:
            continue

        validated_ship = _find_validated_build_ship(
            prior_turn=prior_turn,
            score_turn=score_turn,
            player_id=player_id,
            prior_ship_ids=prior_ship_ids,
            starbase=starbase,
            planet_x=planet.x,
            planet_y=planet.y,
        )
        if validated_ship is None:
            drops += 1
            continue

        hull = hulls_by_id(score_turn).get(validated_ship.hullid)
        if hull is None:
            drops += 1
            continue

        observations.append(
            ShipBuildObservation(
                hull_id=validated_ship.hullid,
                engine_id=validated_ship.engineid,
                beam_id=validated_ship.beamid,
                torpedo_id=validated_ship.torpedoid,
                beam_count=validated_ship.beams,
                launcher_count=validated_ship.torps,
                hull_category=resolve_inference_hull_category(
                    hull,
                    beam_count=validated_ship.beams,
                    launcher_count=validated_ship.torps,
                ),
                ship_limit_band=ship_limit_band,
                race_id=race_id,
                hull_beam_slots=hull.beams,
                hull_launcher_slots=hull.launchers,
            )
        )

    return observations, drops


def _find_validated_build_ship(
    *,
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
    prior_ship_ids: set[int],
    starbase: Starbase,
    planet_x: int,
    planet_y: int,
) -> Ship | None:
    for ship in owned_active_ships(score_turn, player_id):
        if ship.id in prior_ship_ids:
            continue
        if ship.x != planet_x or ship.y != planet_y:
            continue
        if _ship_matches_starbase_order(ship, starbase):
            return ship
    del prior_turn
    return None


def _ship_matches_starbase_order(ship: Ship, starbase: Starbase) -> bool:
    return (
        ship.hullid == starbase.buildhullid
        and ship.engineid == starbase.buildengineid
        and ship.beamid == starbase.buildbeamid
        and ship.torpedoid == starbase.buildtorpedoid
        and ship.beams == starbase.buildbeamcount
        and ship.torps == starbase.buildtorpcount
    )


def _validated_new_ships(
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
    starbases: list[Starbase],
) -> list[Ship]:
    del starbases
    planets_by_id = {planet.id: planet for planet in prior_turn.planets}
    prior_ship_ids = {ship.id for ship in owned_active_ships(prior_turn, player_id)}
    validated: list[Ship] = []
    for starbase in prior_turn.starbases:
        if not starbase.isbuilding:
            continue
        planet = planets_by_id.get(starbase.planetid)
        if planet is None or planet.ownerid != player_id:
            continue
        ship = _find_validated_build_ship(
            prior_turn=prior_turn,
            score_turn=score_turn,
            player_id=player_id,
            prior_ship_ids=prior_ship_ids,
            starbase=starbase,
            planet_x=planet.x,
            planet_y=planet.y,
        )
        if ship is not None:
            validated.append(ship)
    return validated


def _aggregate_histogram_deltas(
    *,
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
    exclude_ship_ids: frozenset[int],
) -> dict[str, int]:
    deltas: dict[str, int] = {}

    deltas["planet_defense_posts_added_total"] = planet_defense_inventory_delta(
        prior_turn, score_turn, player_id
    )
    deltas["starbase_defense_posts_added_total"] = starbase_defense_inventory_delta(
        prior_turn, score_turn, player_id
    )
    deltas["starbase_fighters_added_total"] = starbase_fighter_inventory_delta(
        prior_turn, score_turn, player_id
    )
    deltas["ship_fighters_added_total"] = fighter_load_delta(
        prior_turn,
        score_turn,
        player_id,
        exclude_ship_ids=exclude_ship_ids,
    )

    torp_ids = {torp.id for torp in prior_turn.torpedos} | {torp.id for torp in score_turn.torpedos}
    torp_load_deltas: list[int] = []
    for torp_id in sorted(torp_ids):
        action_id = f"{SHIP_TORPS_LOADED_ACTION_PREFIX}{torp_id}"
        delta = torpedo_load_delta_for_type(
            prior_turn,
            score_turn,
            player_id,
            torp_id,
            exclude_ship_ids=exclude_ship_ids,
        )
        deltas[action_id] = delta
        torp_load_deltas.append(delta)
    deltas[SHIP_TORPS_LOADED_ANY_PRIOR_KEY] = sum(torp_load_deltas)

    transfer = fighter_transfer_counts(prior_turn, score_turn, player_id)
    for action_id in ("fighters_starbase_to_ship", "fighters_ship_to_starbase"):
        if transfer is not None and transfer[0] == action_id and transfer[1] > 0:
            deltas[action_id] = 1
        else:
            deltas[action_id] = 0

    for action_id in AGGREGATE_ACTION_SPECS:
        deltas.setdefault(action_id, 0)

    return deltas


def record_ship_build_slot_fill(observation: ShipBuildObservation, hull) -> str | None:
    del hull
    return record_ship_build_slot_fill_from_observation(observation)


def record_ship_build_slot_fill_from_observation(
    observation: ShipBuildObservation,
) -> str | None:
    beam_full = (
        observation.hull_beam_slots == 0 or observation.beam_count == observation.hull_beam_slots
    )
    launcher_full = (
        observation.hull_launcher_slots == 0
        or observation.launcher_count == observation.hull_launcher_slots
    )
    if beam_full and launcher_full:
        return "full"
    return "partial"


def _score_for_player(turn: TurnInfo, player_id: int) -> Score | None:
    return next((row for row in turn.scores if row.ownerid == player_id), None)


def _has_turn_pair(
    stored_turns: frozenset[int],
    host_turn: int,
    score_turn: int,
) -> bool:
    return host_turn in stored_turns and score_turn in stored_turns


def _merged_inventory_for_player_host_turn(
    *,
    turn_cache: MiningTurnCache,
    game_id: int,
    perspective: int,
    host_turn: int,
    score_turn_number: int,
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
) -> MergedTurnInventory:
    host_perspectives = turn_cache.perspectives_at_turn(game_id, host_turn)
    score_perspectives = turn_cache.perspectives_at_turn(game_id, score_turn_number)
    other_perspectives = sorted(
        p for p in host_perspectives & score_perspectives if p >= 1 and p != perspective
    )
    other_prior = tuple(
        turn_cache.get_turn_info(game_id, other, host_turn) for other in other_perspectives
    )
    other_score = tuple(
        turn_cache.get_turn_info(game_id, other, score_turn_number) for other in other_perspectives
    )
    return merge_turn_inventories(
        case_perspective_prior=prior_turn,
        case_perspective_score=score_turn,
        other_prior_turns=other_prior,
        other_score_turns=other_score,
    )

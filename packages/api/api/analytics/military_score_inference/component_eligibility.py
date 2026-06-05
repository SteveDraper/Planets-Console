"""Shared hull and component eligibility helpers for military score inference."""

from dataclasses import dataclass

from api.analytics.military_score_inference.ship_build_combos import MAX_SHIP_BUILD_TIER
from api.analytics.military_score_inference.ship_build_presets import default_build_components
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import TurnInfo
from api.models.player import Player, Race


@dataclass(frozen=True)
class TurnCatalogContext:
    hulls_by_id: dict[int, Hull]
    engines_by_id: dict[int, Engine]
    beams_by_id: dict[int, Beam]
    torpedos_by_id: dict[int, Torpedo]
    buildable_hull_ids: frozenset[int]
    eligible_engine_ids: frozenset[int]
    eligible_beam_ids: frozenset[int]
    eligible_torp_ids: frozenset[int]


def parse_component_id_csv(component_ids: str) -> frozenset[int]:
    if not component_ids.strip():
        return frozenset()
    return frozenset(int(component_id) for component_id in component_ids.split(",") if component_id)


def player_by_id(turn: TurnInfo, player_id: int) -> Player:
    if turn.player.id == player_id:
        return turn.player
    for player in turn.players:
        if player.id == player_id:
            return player
    raise ValueError(f"unknown player id: {player_id}")


def race_by_id_or_none(turn: TurnInfo, race_id: int) -> Race | None:
    for race in turn.races:
        if race.id == race_id:
            return race
    return None


def buildable_hull_ids_for_player(turn: TurnInfo, player_id: int) -> frozenset[int]:
    player = player_by_id(turn, player_id)
    race = race_by_id_or_none(turn, player.raceid)
    active_hull_ids = parse_component_id_csv(player.activehulls)
    if race is not None:
        eligible_hull_ids = active_hull_ids & (
            parse_component_id_csv(race.hulls) | parse_component_id_csv(race.basehulls)
        )
    else:
        eligible_hull_ids = active_hull_ids
    turn_hull_ids = frozenset(turn.racehulls)
    catalog_hull_ids = frozenset(hull.id for hull in turn.hulls)
    return eligible_hull_ids & turn_hull_ids & catalog_hull_ids


def eligible_component_ids_for_player(
    *,
    active_component_csv: str,
    turn_catalog_ids: frozenset[int],
) -> frozenset[int]:
    """Return active components intersected with the turn catalog, jumping when active is empty."""
    active_ids = parse_component_id_csv(active_component_csv)
    if not active_ids:
        return turn_catalog_ids
    return active_ids & turn_catalog_ids


def _default_component_id_set(component) -> frozenset[int]:
    if component is None:
        return frozenset()
    return frozenset({component.id})


def turn_catalog_context_for_tier(
    turn: TurnInfo,
    player_id: int,
    tier: int,
) -> TurnCatalogContext:
    if tier < 0 or tier > MAX_SHIP_BUILD_TIER:
        raise ValueError(f"ship build tier must be between 0 and {MAX_SHIP_BUILD_TIER}, got {tier}")

    hulls_by_id = {hull.id: hull for hull in turn.hulls}
    engines_by_id = {engine.id: engine for engine in turn.engines}
    beams_by_id = {beam.id: beam for beam in turn.beams}
    torpedos_by_id = {torpedo.id: torpedo for torpedo in turn.torpedos}
    player = player_by_id(turn, player_id)
    defaults = default_build_components(
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
    )
    turn_engine_ids = frozenset(engines_by_id)
    turn_beam_ids = frozenset(beams_by_id)
    turn_torp_ids = frozenset(torpedos_by_id)

    if tier == 0:
        eligible_engine_ids = _default_component_id_set(defaults.engine)
    elif tier >= MAX_SHIP_BUILD_TIER:
        eligible_engine_ids = turn_engine_ids
    else:
        eligible_engine_ids = eligible_component_ids_for_player(
            active_component_csv=player.activeengines,
            turn_catalog_ids=turn_engine_ids,
        )

    if tier <= 1:
        eligible_beam_ids = _default_component_id_set(defaults.beam)
    elif tier >= MAX_SHIP_BUILD_TIER:
        eligible_beam_ids = turn_beam_ids
    else:
        eligible_beam_ids = eligible_component_ids_for_player(
            active_component_csv=player.activebeams,
            turn_catalog_ids=turn_beam_ids,
        )

    if tier <= 2:
        eligible_torp_ids = _default_component_id_set(defaults.torpedo)
    elif tier >= MAX_SHIP_BUILD_TIER:
        eligible_torp_ids = turn_torp_ids
    else:
        eligible_torp_ids = eligible_component_ids_for_player(
            active_component_csv=player.activetorps,
            turn_catalog_ids=turn_torp_ids,
        )

    return TurnCatalogContext(
        hulls_by_id=hulls_by_id,
        engines_by_id=engines_by_id,
        beams_by_id=beams_by_id,
        torpedos_by_id=torpedos_by_id,
        buildable_hull_ids=buildable_hull_ids_for_player(turn, player_id),
        eligible_engine_ids=eligible_engine_ids,
        eligible_beam_ids=eligible_beam_ids,
        eligible_torp_ids=eligible_torp_ids,
    )


def turn_catalog_context_for_player(turn: TurnInfo, player_id: int) -> TurnCatalogContext:
    """Full active-or-jump eligibility (tier 3 semantics)."""
    return turn_catalog_context_for_tier(turn, player_id, tier=3)

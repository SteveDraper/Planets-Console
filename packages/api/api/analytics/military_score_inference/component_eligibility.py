"""Shared hull and component eligibility helpers for military score inference."""

from api.models.game import TurnInfo
from api.models.player import Player, Race


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
    turn: TurnInfo,
    player_id: int,
    *,
    active_component_csv: str,
    turn_catalog_ids: frozenset[int],
) -> frozenset[int]:
    """Return active components intersected with the turn catalog, jumping when active is empty."""
    active_ids = parse_component_id_csv(active_component_csv)
    if not active_ids:
        return turn_catalog_ids
    return active_ids & turn_catalog_ids

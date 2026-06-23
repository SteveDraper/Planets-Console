"""Turn snapshot lookups shared by hull catalog and component eligibility."""

from collections.abc import Iterator

from api.models.game import TurnInfo
from api.models.player import Player, Race


def parse_component_id_csv(component_ids: str) -> frozenset[int]:
    if not component_ids.strip():
        return frozenset()
    return frozenset(int(component_id) for component_id in component_ids.split(",") if component_id)


def iter_turn_players(turn: TurnInfo) -> Iterator[Player]:
    """Yield perspective player then other players, deduped by id (perspective wins)."""
    seen: set[int] = set()
    for player in (turn.player, *turn.players):
        if player.id in seen:
            continue
        seen.add(player.id)
        yield player


def players_by_id(turn: TurnInfo) -> dict[int, Player]:
    """Map player id to Player for perspective player plus turn.players, deduped."""
    return {player.id: player for player in iter_turn_players(turn)}


def player_by_id(turn: TurnInfo, player_id: int) -> Player:
    player = players_by_id(turn).get(player_id)
    if player is None:
        raise ValueError(f"unknown player id: {player_id}")
    return player


def race_by_id_or_none(turn: TurnInfo, race_id: int) -> Race | None:
    for race in turn.races:
        if race.id == race_id:
            return race
    return None

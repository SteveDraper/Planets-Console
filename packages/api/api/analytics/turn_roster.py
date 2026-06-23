"""Turn snapshot player roster helpers shared across turn analytics."""

from collections.abc import Iterator

from api.models.game import TurnInfo
from api.models.player import Player


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

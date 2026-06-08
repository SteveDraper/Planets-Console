"""Turn snapshot lookups shared by hull catalog and component eligibility."""

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

"""Turn snapshot lookups shared by hull catalog and component eligibility."""

from api.analytics.turn_roster import player_by_id
from api.models.game import TurnInfo
from api.models.player import Race

__all__ = [
    "parse_component_id_csv",
    "player_by_id",
    "race_by_id_or_none",
]


def parse_component_id_csv(component_ids: str) -> frozenset[int]:
    if not component_ids.strip():
        return frozenset()
    return frozenset(int(component_id) for component_id in component_ids.split(",") if component_id)


def race_by_id_or_none(turn: TurnInfo, race_id: int) -> Race | None:
    for race in turn.races:
        if race.id == race_id:
            return race
    return None

"""Core scoreboard analytic."""

from api.models.game import TurnInfo

ANALYTIC_ID = "scores"


def get_scores_table(turn: TurnInfo) -> dict:
    """Return scoreboard values for each player in a turn."""
    players_by_id = {player.id: player for player in [turn.player, *turn.players]}
    races_by_id = {race.id: race for race in turn.races}

    rows = []
    for score in turn.scores:
        player = players_by_id.get(score.ownerid)
        race = races_by_id.get(player.raceid) if player is not None else None
        if race is not None and player is not None:
            race_player = f"{race.name} ({player.username})"
        elif player is not None:
            race_player = player.username
        else:
            race_player = f"Player {score.ownerid}"
        rows.append(
            {
                "playerId": score.ownerid,
                "racePlayer": race_player,
                "planets": {"value": score.planets, "change": score.planetchange},
                "starbases": {"value": score.starbases, "change": score.starbasechange},
                "warShips": {"value": score.capitalships, "change": score.shipchange},
                "freighters": {"value": score.freighters, "change": score.freighterchange},
                "military": {
                    "value": score.militaryscore,
                    "change": score.militarychange,
                },
                "priorityPoints": {
                    "value": score.prioritypoints,
                    "change": score.prioritypointchange,
                },
            }
        )
    return {"analyticId": ANALYTIC_ID, "rows": rows}

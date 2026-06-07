"""Core scoreboard analytic."""

from collections.abc import Callable

from api.analytics.military_score_inference.analytic import (
    infer_military_score_build,
    run_inference_with_artifacts,
)
from api.analytics.options import TurnAnalyticsOptions
from api.models.game import TurnInfo

ANALYTIC_ID = "scores"


def _score_row(
    score,
    *,
    players_by_id: dict[int, object],
    races_by_id: dict[int, object],
) -> dict[str, object]:
    player = players_by_id.get(score.ownerid)
    race = races_by_id.get(player.raceid) if player is not None else None
    if race is not None and player is not None:
        race_player = f"{race.name} ({player.username})"
    elif player is not None:
        race_player = player.username
    else:
        race_player = f"Player {score.ownerid}"
    return {
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


def get_scores_table(
    turn: TurnInfo,
    options: TurnAnalyticsOptions | None = None,
) -> dict:
    """Return scoreboard values for each player in a turn."""
    _ = options or TurnAnalyticsOptions()
    players_by_id = {player.id: player for player in [turn.player, *turn.players]}
    races_by_id = {race.id: race for race in turn.races}

    rows = [
        _score_row(score, players_by_id=players_by_id, races_by_id=races_by_id)
        for score in turn.scores
    ]
    return {"analyticId": ANALYTIC_ID, "rows": rows}


def get_scores_row_inference(
    turn: TurnInfo,
    player_id: int,
    *,
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None,
) -> dict[str, object]:
    """Run military score build inference for one scoreboard row."""
    score = next((row for row in turn.scores if row.ownerid == player_id), None)
    if score is None:
        return {
            "playerId": player_id,
            "status": "player_not_found",
            "summary": f"No score row for player {player_id}",
            "solutionCount": 0,
            "isComplete": True,
            "solutions": [],
            "diagnostics": {"playerId": player_id, "turn": turn.settings.turn},
        }
    if load_scoreboard_turn is None:
        inference = infer_military_score_build(score, turn)
    else:
        inference, _, _ = run_inference_with_artifacts(
            score,
            turn,
            load_scoreboard_turn=load_scoreboard_turn,
        )
    return {"playerId": player_id, **inference}

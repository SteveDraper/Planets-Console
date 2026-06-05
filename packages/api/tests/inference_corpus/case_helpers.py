"""Small helpers shared by inference corpus harness modules."""

from api.models.player import Score


def score_for_player(scores: list[Score], player_id: int, case_id: str) -> Score:
    for score in scores:
        if score.ownerid == player_id:
            return score
    raise ValueError(f"case {case_id}: no score row for playerId {player_id}")

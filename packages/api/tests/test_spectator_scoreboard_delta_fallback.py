"""Spectator scoreboard rows omit change columns; infer deltas from prior-row totals."""

from pathlib import Path

import pytest
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_target import prior_scoreboard_row_score
from api.serialization.turn import turn_info_from_json

DATA_ROOT = Path(__file__).resolve().parents[2] / ".data" / "games" / "673864" / "0" / "turns"


def _load_store_turn(turn_number: int):
    with DATA_ROOT.joinpath(f"{turn_number}.json").open(encoding="utf-8") as handle:
        return turn_info_from_json(__import__("json").load(handle))


@pytest.mark.skipif(not DATA_ROOT.joinpath("3.json").is_file(), reason="local store only")
def test_spectator_turn3_derives_deltas_from_prior_row_totals():
    turn = _load_store_turn(3)
    prior_turn = _load_store_turn(2)
    score = next(s for s in turn.scores if s.ownerid == 1)
    prior_score = next(s for s in prior_turn.scores if s.ownerid == 1)

    assert score.militarychange == 0
    assert score.shipchange == 0
    assert score.militaryscore - prior_score.militaryscore == 855
    assert score.capitalships - prior_score.capitalships == 1

    def load_scoreboard_turn(turn_number: int):
        return _load_store_turn(turn_number)

    observation = build_inference_observation(
        score,
        turn,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    assert observation.scoreboard_delta_source == "prior_row_total_diff"
    assert observation.military_delta_2x == 2 * 855
    assert observation.warship_delta == 1
    assert prior_scoreboard_row_score(score, turn, load_scoreboard_turn) == prior_score

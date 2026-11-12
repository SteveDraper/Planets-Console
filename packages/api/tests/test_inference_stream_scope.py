"""``InferenceStreamScope`` projections from a root scope and from a session."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.scope import WILDCARD, ComputeScope

from tests.scores_row_lifecycle_test_helpers import _session_for_player


def _root(**overrides: object) -> ComputeScope:
    fields: dict[str, object] = {
        "analytic_id": SCORES_ANALYTIC_ID,
        "game_id": 628580,
        "perspective": 3,
        "turn": 41,
        "player_id": 7,
    }
    fields.update(overrides)
    return ComputeScope(**fields)


def test_from_root_reads_game_perspective_and_turn():
    assert InferenceStreamScope.from_root(_root()) == InferenceStreamScope(
        game_id=628580,
        perspective=3,
        turn_number=41,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"player_id": WILDCARD},
        {"turn": WILDCARD},
        {"perspective": WILDCARD},
    ],
    ids=["wildcard-player", "wildcard-turn", "wildcard-perspective"],
)
def test_from_root_rejects_a_scope_that_does_not_name_one_player_turn(overrides):
    with pytest.raises(ValueError, match="concrete"):
        InferenceStreamScope.from_root(_root(**overrides))


def test_from_session_reads_the_session_scope_fields(sample_turn):
    player_id = sample_turn.scores[0].ownerid
    session = _session_for_player(sample_turn, player_id=player_id, game_id=11, perspective=2)

    assert InferenceStreamScope.from_session(session) == InferenceStreamScope(
        game_id=11,
        perspective=2,
        turn_number=sample_turn.settings.turn,
    )

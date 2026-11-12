"""``InferenceStreamScope`` and ``InferenceRowScope`` projections from root scopes and sessions."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.inference_stream_scope import (
    InferenceRowScope,
    InferenceStreamScope,
)
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


def test_row_scope_from_root_keeps_the_player_and_round_trips():
    row_scope = InferenceRowScope.from_root(_root())

    assert row_scope == InferenceRowScope(
        stream_scope=InferenceStreamScope(game_id=628580, perspective=3, turn_number=41),
        player_id=7,
    )
    assert row_scope.root_scope() == _root()


@pytest.mark.parametrize(
    "overrides",
    [
        {"player_id": WILDCARD},
        {"turn": WILDCARD},
        {"perspective": WILDCARD},
    ],
    ids=["wildcard-player", "wildcard-turn", "wildcard-perspective"],
)
def test_row_scope_try_from_root_is_none_for_a_wider_scope(overrides):
    assert InferenceRowScope.try_from_root(_root(**overrides)) is None
    with pytest.raises(ValueError, match="concrete"):
        InferenceRowScope.from_root(_root(**overrides))


def test_row_scope_from_session_matches_the_row_scope_of_its_root(sample_turn):
    player_id = sample_turn.scores[0].ownerid
    session = _session_for_player(sample_turn, player_id=player_id, game_id=11, perspective=2)

    row_scope = InferenceRowScope.from_session(session)

    assert row_scope.player_id == player_id
    assert InferenceRowScope.from_root(row_scope.root_scope()) == row_scope

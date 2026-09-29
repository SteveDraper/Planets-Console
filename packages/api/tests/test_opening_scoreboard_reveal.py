"""Non-accelerated turn 2 deltas exclude the homeworld baseline.

Accelerated games keep reported change columns on the first reliable row.
"""

from dataclasses import replace

import pytest
from api.analytics.fleet.scoreboard_placeholder_targets import (
    ScoreboardPlaceholderTarget,
    scoreboard_placeholder_targets,
)
from api.analytics.military_score_inference.accelerated_start import (
    accelerated_inference_segments,
)
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.ship_transfer_families import (
    public_scoreboard_rows_from_scores,
)
from api.concepts.accelerated_scoreboard import (
    OPENING_BASELINE_DELTA_SOURCE,
    homeworld_baseline_military_2x,
    reported_scoreboard_deltas,
    starting_scoreboard_snapshot,
)
from api.concepts.races import HORWASP_RACE_ID

from tests.fixtures.military_score_inference import with_score_owners_in_roster


def _score(template, **fields):
    return replace(
        template,
        prioritypoints=0,
        prioritypointchange=0,
        inventoryscore=0,
        inventorychange=0,
        percent=0.0,
        percentchange=0.0,
        victoryscore=0,
        victoryscorechange=0,
        **fields,
    )


def _turn(sample_turn, *, turn_number: int, acceleratedturns: int, scores):
    return with_score_owners_in_roster(
        replace(
            sample_turn,
            settings=replace(
                sample_turn.settings,
                turn=turn_number,
                acceleratedturns=acceleratedturns,
                homeworldhasstarbase=True,
            ),
            scores=tuple(scores),
        )
    )


def _horwasp(template, *, freighters: int):
    """Homeworld plus ``freighters`` freighters, each showing up from 0."""
    return _score(
        template,
        ownerid=52,
        turn=2,
        militaryscore=0,
        militarychange=0,
        capitalships=0,
        shipchange=0,
        freighters=freighters,
        freighterchange=freighters,
        starbases=0,
        starbasechange=0,
        planets=1,
        planetchange=1,
    )


def _horwasp_turn(sample_turn, score):
    player = replace(sample_turn.players[0], id=score.ownerid, raceid=HORWASP_RACE_ID)
    turn = _turn(sample_turn, turn_number=2, acceleratedturns=0, scores=[score])
    return replace(turn, players=(player,))


def _forger(template, *, turn_number: int):
    """One new freighter. Scoreboard change columns are deltas from 0."""
    return _score(
        template,
        ownerid=51,
        turn=turn_number,
        militaryscore=2110,
        militarychange=2110,
        capitalships=0,
        shipchange=0,
        freighters=2,
        freighterchange=2,
        starbases=1,
        starbasechange=1,
        planets=1,
        planetchange=1,
    )


def _mapdot(template, *, turn_number: int):
    """One Meteor (military 2008) plus the starting freighter showing up from 0."""
    return _score(
        template,
        ownerid=35,
        turn=turn_number,
        militaryscore=4118,
        militarychange=4118,
        capitalships=1,
        shipchange=1,
        freighters=1,
        freighterchange=1,
        starbases=1,
        starbasechange=1,
        planets=1,
        planetchange=1,
    )


def test_non_accelerated_turn2_forger_is_one_freighter(sample_turn):
    template = sample_turn.scores[0]
    forger = _forger(template, turn_number=2)
    turn = _turn(sample_turn, turn_number=2, acceleratedturns=0, scores=[forger])

    observation = build_inference_observation(forger, turn)

    assert homeworld_baseline_military_2x(turn.settings) == 4220
    assert observation.scoreboard_delta_source == OPENING_BASELINE_DELTA_SOURCE
    assert observation.military_delta_2x == 0
    assert observation.warship_delta == 0
    assert observation.freighter_delta == 1
    assert observation.starbase_delta == 0
    assert observation.planet_delta == 0
    targets = scoreboard_placeholder_targets(forger, turn)
    assert targets == (
        ScoreboardPlaceholderTarget(host_turn=2, warship_delta=0, freighter_delta=1),
    )


def test_non_accelerated_turn2_mapdot_is_one_warship(sample_turn):
    template = sample_turn.scores[0]
    mapdot = _mapdot(template, turn_number=2)
    turn = _turn(sample_turn, turn_number=2, acceleratedturns=0, scores=[mapdot])

    observation = build_inference_observation(mapdot, turn)

    assert observation.military_delta_2x == 4016
    assert observation.warship_delta == 1
    assert observation.freighter_delta == 0
    assert observation.starbase_delta == 0
    assert observation.planet_delta == 0
    targets = scoreboard_placeholder_targets(mapdot, turn)
    assert len(targets) == 1
    assert targets[0].warship_delta == 1
    assert targets[0].freighter_delta == 0


def test_non_accelerated_turn2_public_rows_use_the_same_baseline(sample_turn):
    template = sample_turn.scores[0]
    forger = _forger(template, turn_number=2)
    mapdot = _mapdot(template, turn_number=2)
    turn = _turn(
        sample_turn,
        turn_number=2,
        acceleratedturns=0,
        scores=[forger, mapdot],
    )

    peers = public_scoreboard_rows_from_scores(
        turn.scores,
        this_player_id=forger.ownerid,
        turn=turn,
    )

    assert len(peers) == 1
    assert peers[0].player_id == mapdot.ownerid
    assert peers[0].military_delta_2x == 4016
    assert peers[0].warship_delta == 1
    assert peers[0].freighter_delta == 0
    assert peers[0].planet_delta == 0
    assert peers[0].starbase_delta == 0


def test_non_accelerated_turn2_without_homeworld_starbase_keeps_the_homeworld(sample_turn):
    template = sample_turn.scores[0]
    score = _score(
        template,
        ownerid=51,
        turn=2,
        militaryscore=0,
        militarychange=0,
        capitalships=0,
        shipchange=0,
        freighters=0,
        freighterchange=0,
        starbases=0,
        starbasechange=0,
        planets=1,
        planetchange=1,
    )
    turn = _turn(sample_turn, turn_number=2, acceleratedturns=0, scores=[score])
    turn = replace(turn, settings=replace(turn.settings, homeworldhasstarbase=False))

    baseline = starting_scoreboard_snapshot(turn.settings)
    deltas = reported_scoreboard_deltas(score, turn)

    assert baseline.planets == 1
    assert baseline.starbases == 0
    assert deltas.delta_source == OPENING_BASELINE_DELTA_SOURCE
    assert deltas.planet_delta == 0
    assert deltas.starbase_delta == 0
    assert deltas.freighter_delta == 0


def test_horwasp_turn2_subtracts_the_starbaseless_baseline(sample_turn):
    template = sample_turn.scores[0]
    horwasp = _horwasp(template, freighters=1)
    turn = _horwasp_turn(sample_turn, horwasp)

    observation = build_inference_observation(horwasp, turn)

    assert observation.scoreboard_delta_source == OPENING_BASELINE_DELTA_SOURCE
    assert observation.military_delta_2x == 0
    assert observation.warship_delta == 0
    assert observation.freighter_delta == 0
    assert observation.planet_delta == 0
    assert observation.starbase_delta == 0
    assert scoreboard_placeholder_targets(horwasp, turn) is None


def test_horwasp_turn2_extra_freighter_is_one_freighter(sample_turn):
    template = sample_turn.scores[0]
    horwasp = _horwasp(template, freighters=2)
    turn = _horwasp_turn(sample_turn, horwasp)

    deltas = reported_scoreboard_deltas(horwasp, turn)

    assert deltas.delta_source == OPENING_BASELINE_DELTA_SOURCE
    assert deltas.military_delta_2x == 0
    assert deltas.freighter_delta == 1
    assert deltas.starbase_delta == 0
    assert deltas.planet_delta == 0


def test_turn2_score_owner_missing_from_roster_raises(sample_turn):
    template = sample_turn.scores[0]
    forger = _forger(template, turn_number=2)
    turn = _turn(sample_turn, turn_number=2, acceleratedturns=0, scores=[forger])
    turn = replace(turn, players=())

    with pytest.raises(ValueError, match="51"):
        reported_scoreboard_deltas(forger, turn)


def test_later_turn_does_not_need_the_score_owner_in_roster(sample_turn):
    template = sample_turn.scores[0]
    forger = _forger(template, turn_number=4)
    turn = _turn(sample_turn, turn_number=4, acceleratedturns=0, scores=[forger])
    turn = replace(turn, players=())

    deltas = reported_scoreboard_deltas(forger, turn)

    assert deltas.delta_source == "reported_change_fields"
    assert deltas.freighter_delta == forger.freighterchange


def test_non_accelerated_later_turn_keeps_change_columns(sample_turn):
    template = sample_turn.scores[0]
    score = _score(
        template,
        ownerid=51,
        turn=4,
        militaryscore=2300,
        militarychange=190,
        capitalships=1,
        shipchange=1,
        freighters=2,
        freighterchange=0,
        starbases=1,
        starbasechange=0,
        planets=2,
        planetchange=1,
    )
    turn = _turn(sample_turn, turn_number=4, acceleratedturns=0, scores=[score])

    observation = build_inference_observation(score, turn)

    assert observation.scoreboard_delta_source == "reported_change_fields"
    assert observation.military_delta_2x == 2 * 190
    assert observation.warship_delta == 1
    assert observation.freighter_delta == 0
    assert observation.planet_delta == 1
    assert observation.starbase_delta == 0


def test_accelerated_first_reliable_turn_keeps_reported_change_columns(sample_turn):
    """Same from-zero looking totals must not take the opening-reveal path."""
    template = sample_turn.scores[0]
    score = _mapdot(template, turn_number=3)
    turn = _turn(sample_turn, turn_number=3, acceleratedturns=3, scores=[score])

    observation = build_inference_observation(score, turn)
    segments = accelerated_inference_segments(score, turn)

    assert observation.scoreboard_delta_source == "reported_change_fields"
    assert observation.military_delta_2x == 2 * score.militarychange
    assert observation.warship_delta == score.shipchange
    assert observation.freighter_delta == score.freighterchange
    assert segments is not None
    reported = segments[-1]
    assert reported.military_delta_2x == 2 * score.militarychange
    assert reported.warship_delta == score.shipchange
    assert reported.freighter_delta == score.freighterchange
    targets = scoreboard_placeholder_targets(score, turn)
    assert any(target.warship_delta == 1 and target.freighter_delta == 1 for target in targets)

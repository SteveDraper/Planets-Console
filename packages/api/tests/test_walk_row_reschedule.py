"""A live walk row's own scope, and rescheduling the rows whose own scope a settle stopped."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.fleet_table_stream_registry import get_fleet_table_stream_registry
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    get_inference_table_stream_registry,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.analytics.walk_row_reschedule import reschedule_walk_rows, rows_with_stopped_scope
from api.analytics.walk_shell_watch import live_walk_shells
from api.compute.errors import ComputeScopeAbortedError
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.compute.scope import ComputeScope
from api.exceptions import DiscardedWorkRefused

from tests.on_walk_live_helpers import attach_stream
from tests.walk_band_helpers import no_live_streams

GAME_ID = 10
PERSPECTIVE = 2
STREAM_TURN = 8


@pytest.fixture(autouse=True)
def _no_live_streams() -> Iterator[None]:
    yield from no_live_streams()


def _row_scope(analytic_id: str, player_id: int, *, turn: int = STREAM_TURN) -> ComputeScope:
    return ComputeScope(
        analytic_id=analytic_id,
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        turn=turn,
        player_id=player_id,
    )


def _open_fleet_and_scoreboard_streams(player_ids: list[int]):
    fleet = attach_stream(
        get_fleet_table_stream_registry(),
        FleetTableStreamScope(GAME_ID, PERSPECTIVE, STREAM_TURN),
        None,
        None,
        player_ids,
    )
    scoreboard = attach_stream(
        get_inference_table_stream_registry(),
        InferenceStreamScope(GAME_ID, PERSPECTIVE, STREAM_TURN),
        None,
        None,
        player_ids,
    )
    return fleet, scoreboard


def test_a_rows_own_scope_is_its_streams_analytic_at_the_stream_turn_for_its_player():
    _open_fleet_and_scoreboard_streams([1, 2])

    assert {shell.own_scope for shell in live_walk_shells()} == {
        _row_scope(FLEET_ANALYTIC_ID, 1),
        _row_scope(FLEET_ANALYTIC_ID, 2),
        _row_scope(SCORES_ANALYTIC_ID, 1),
        _row_scope(SCORES_ANALYTIC_ID, 2),
    }


def test_only_rows_whose_own_scope_was_stopped_are_selected():
    _open_fleet_and_scoreboard_streams([1, 2])
    stopped = frozenset(
        {
            _row_scope(FLEET_ANALYTIC_ID, 1),
            # A hop below the row's turn is not the row's own scope.
            _row_scope(FLEET_ANALYTIC_ID, 2, turn=STREAM_TURN - 1),
            _row_scope(SCORES_ANALYTIC_ID, 2),
        }
    )

    rows = rows_with_stopped_scope(stopped, live_walk_shells())

    assert {row.own_scope for row in rows} == {
        _row_scope(FLEET_ANALYTIC_ID, 1),
        _row_scope(SCORES_ANALYTIC_ID, 2),
    }


def test_each_selected_row_is_rescheduled_through_its_own_stream():
    fleet, scoreboard = _open_fleet_and_scoreboard_streams([1, 2])
    stopped = frozenset({_row_scope(FLEET_ANALYTIC_ID, 2), _row_scope(SCORES_ANALYTIC_ID, 1)})

    reschedule_walk_rows(rows_with_stopped_scope(stopped, live_walk_shells()))

    assert fleet.rescheduled_player_ids == [2]
    assert scoreboard.rescheduled_player_ids == [1]


@pytest.mark.parametrize(
    ("state", "error", "is_intentional_abort"),
    [
        ("failed", ComputeScopeAbortedError("aborted"), True),
        ("failed", DiscardedWorkRefused("discarded"), False),
        ("failed", RuntimeError("the step failed"), False),
        ("complete", None, False),
        ("parked", None, False),
    ],
)
def test_only_a_failure_with_the_abort_error_is_an_intentional_abort(
    state, error, is_intentional_abort
):
    snapshot = ScopeLifecycleSnapshot(
        scope=_row_scope(FLEET_ANALYTIC_ID, 1),
        state=state,
        execution_generation=0,
        result_wire=None,
        error=error,
    )

    assert snapshot.is_intentional_abort is is_intentional_abort

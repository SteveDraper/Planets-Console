"""A durable evidence bump's settle policy, watched turns and wake targets."""

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
from api.compute.errors import ComputeScopeAbortedError
from api.compute.in_flight_settle import (
    InFlightCandidate,
    PlayerWork,
    RunningDisposition,
    UnstartedDisposition,
)
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
from api.compute.orchestrator_state import NodeState
from api.compute.running_step import RunningStepDisposition
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.services.evidence_bump import (
    BumpSettlePolicy,
    DurableRecompute,
    FleetScopeWake,
    HeldRecompute,
    LiveRowWake,
    bump_watched_turns,
    player_live_walk_rows,
)

from tests.on_walk_live_helpers import attach_stream
from tests.walk_band_helpers import no_live_streams

GAME_ID = 1
PERSPECTIVE = 1
PLAYER_ID = 7
OTHER_PLAYER_ID = 8


@pytest.fixture(autouse=True)
def _no_live_streams() -> Iterator[None]:
    yield from no_live_streams()


def _scope(turn: int, analytic_id: str = FLEET_ANALYTIC_ID, player_id: int = PLAYER_ID):
    return ComputeScope(
        analytic_id=analytic_id,
        game_id=GAME_ID,
        perspective=PERSPECTIVE,
        turn=turn,
        player_id=player_id,
    )


def _candidate(turn: int, *, on_walk: bool) -> InFlightCandidate:
    return InFlightCandidate(
        scope=_scope(turn),
        submission_open=SubmissionOpen(
            open_turn=turn, backfill_earlier_turns=on_walk, on_walk=on_walk
        ),
    )


def _open_rows(turn: int, *, player_ids: list[int], scoreboard: bool = True) -> None:
    attach_stream(
        get_fleet_table_stream_registry(),
        FleetTableStreamScope(GAME_ID, PERSPECTIVE, turn),
        None,
        None,
        player_ids,
    )
    if scoreboard:
        attach_stream(
            get_inference_table_stream_registry(),
            InferenceStreamScope(GAME_ID, PERSPECTIVE, turn),
            None,
            None,
            player_ids,
        )


# --- BumpSettlePolicy ---


@pytest.mark.parametrize(
    ("turn", "on_walk", "running"),
    [
        (40, False, RunningDisposition.KEEP),
        (40, True, RunningDisposition.ABORT),
        (39, False, RunningDisposition.ABORT),
        (39, True, RunningDisposition.ABORT),
    ],
)
def test_the_bump_keeps_only_running_off_walk_work_on_a_watched_turn(turn, on_walk, running):
    policy = BumpSettlePolicy(watched_turns=frozenset({40}))

    assert policy.running(_candidate(turn, on_walk=on_walk)) is running
    assert policy.unstarted(_candidate(turn, on_walk=on_walk)) is UnstartedDisposition.ABORT


def test_with_nothing_watched_the_bump_keeps_nothing():
    policy = BumpSettlePolicy(watched_turns=frozenset())

    assert policy.running(_candidate(40, on_walk=False)) is RunningDisposition.ABORT


def test_the_bump_aborts_a_replaced_dependency_of_a_kept_running_node():
    """A running node's inputs were complete when it was dispatched, so it keeps none alive."""
    orchestrator = ComputeOrchestrator(compute_registry={})
    replaced_prior = _put_fleet(orchestrator, 39, state="ready")
    running_row = _put_fleet(orchestrator, 40, state="running", dependency_scopes=(replaced_prior,))

    stopped = orchestrator.settle_in_flight_work(
        PlayerWork(
            game_id=GAME_ID,
            perspective=PERSPECTIVE,
            player_id=PLAYER_ID,
            analytic_ids=frozenset({FLEET_ANALYTIC_ID}),
        ),
        BumpSettlePolicy(watched_turns=frozenset({40})),
    )

    assert stopped == frozenset({replaced_prior})
    assert isinstance(orchestrator.nodes[replaced_prior].error, ComputeScopeAbortedError)
    assert replaced_prior not in orchestrator._ready_queue
    assert orchestrator.nodes[running_row].state == "running"
    assert orchestrator.nodes[running_row].running_step is RunningStepDisposition.CONTINUE


def _put_fleet(
    orchestrator: ComputeOrchestrator,
    turn: int,
    *,
    state: NodeState,
    dependency_scopes: tuple[ComputeScope, ...] = (),
) -> ComputeScope:
    scope = _scope(turn)
    orchestrator.nodes[scope] = ComputeNodeRun(
        scope=scope,
        dependency_scopes=dependency_scopes,
        state=state,
        submission_open=SubmissionOpen(),
    )
    if state == "ready":
        orchestrator._ready_queue.append(scope)
    return scope


# --- Watched turns and the player's live rows ---


def test_the_player_live_rows_are_that_players_rows_in_the_game_and_perspective():
    _open_rows(40, player_ids=[PLAYER_ID, OTHER_PLAYER_ID])
    attach_stream(
        get_fleet_table_stream_registry(),
        FleetTableStreamScope(GAME_ID, PERSPECTIVE + 1, 40),
        None,
        None,
        [PLAYER_ID],
    )

    rows = player_live_walk_rows(GAME_ID, PERSPECTIVE, PLAYER_ID)

    assert {row.own_scope for row in rows} == {
        _scope(40),
        _scope(40, SCORES_ANALYTIC_ID),
    }


@pytest.mark.parametrize(("backfill_enabled", "watched"), [(False, {38, 40}), (True, set())])
def test_the_bump_watches_live_row_turns_only_with_the_setting_off(backfill_enabled, watched):
    _open_rows(38, player_ids=[PLAYER_ID])
    _open_rows(40, player_ids=[PLAYER_ID], scoreboard=False)

    rows = player_live_walk_rows(GAME_ID, PERSPECTIVE, PLAYER_ID)

    assert bump_watched_turns(backfill_enabled=backfill_enabled, live_rows=rows) == watched
    assert DurableRecompute(host_turn=40, backfill_enabled=backfill_enabled).settle_policy(
        rows
    ) == BumpSettlePolicy(watched_turns=frozenset(watched))


# --- Wake targets ---


@pytest.mark.parametrize("backfill_enabled", [False, True])
def test_a_durable_bump_wakes_live_rows_from_the_host_turn_and_rows_it_stopped(
    backfill_enabled,
):
    for turn in (37, 38, 40, 41):
        _open_rows(turn, player_ids=[PLAYER_ID])
    rows = player_live_walk_rows(GAME_ID, PERSPECTIVE, PLAYER_ID)
    stopped = frozenset(
        {
            _scope(38),
            # Not a live row's own root: nothing to wake for it.
            _scope(36),
        }
    )

    targets = DurableRecompute(host_turn=40, backfill_enabled=backfill_enabled).wake_targets(
        known_turns=frozenset({40, 41, 42}),
        stopped=stopped,
        live_rows=rows,
    )

    assert all(isinstance(target, LiveRowWake) for target in targets)
    assert {target.row.own_scope for target in targets} == {
        _scope(38),
        _scope(40),
        _scope(40, SCORES_ANALYTIC_ID),
        _scope(41),
        _scope(41, SCORES_ANALYTIC_ID),
    }


def test_a_durable_bump_with_no_live_row_wakes_nothing():
    targets = DurableRecompute(host_turn=40, backfill_enabled=True).wake_targets(
        known_turns=frozenset({40, 41}),
        stopped=frozenset({_scope(40)}),
        live_rows=(),
    )

    assert targets == ()


def test_held_admission_settles_nothing_and_wakes_every_known_fleet_turn():
    _open_rows(41, player_ids=[PLAYER_ID])
    held = HeldRecompute(game_id=GAME_ID, perspective=PERSPECTIVE, player_id=PLAYER_ID)
    rows = player_live_walk_rows(GAME_ID, PERSPECTIVE, PLAYER_ID)

    assert held.settle_policy(rows) is None
    assert held.wake_targets(
        known_turns=frozenset({42, 40}), stopped=frozenset(), live_rows=rows
    ) == (FleetScopeWake(scope=_scope(40)), FleetScopeWake(scope=_scope(42)))

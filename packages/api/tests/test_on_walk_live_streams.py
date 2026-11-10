"""Live-stream on-walk submission: immediate and deferred shell walks per player."""

from __future__ import annotations

from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.fleet_table_stream_registry import (
    get_fleet_table_stream_registry,
    reset_fleet_table_stream_registry_for_tests,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    get_inference_table_stream_registry,
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.on_walk_live import submit_on_walks_for_live_streams
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeNodeRun
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.serialization.backfill_earlier_turns import (
    backfill_earlier_turns_document,
    backfill_earlier_turns_store_key,
)

from tests.export_chain_test_fixtures import enable_backfill_earlier_turns
from tests.off_mode_catch_up_helpers import context_at_turn
from tests.on_walk_helpers import fleet_persistence, held_pool_orchestrator, shell_scope
from tests.on_walk_live_helpers import attach_stream, recording_orchestrator, roster_player_ids
from tests.scores_exports_helpers import first_player_id


def test_live_streams_submit_one_force_fresh_walk_per_player(sample_turn, monkeypatch):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_ids = roster_player_ids(host)
    fleet_scope = FleetTableStreamScope(ctx.game_id, ctx.perspective, 10)
    scores_scope = InferenceStreamScope(ctx.game_id, ctx.perspective, 10)
    fleet = attach_stream(get_fleet_table_stream_registry(), fleet_scope, host, ctx, player_ids)
    scores = attach_stream(
        get_inference_table_stream_registry(), scores_scope, host, ctx, player_ids
    )
    orchestrator, submitted = recording_orchestrator(monkeypatch)
    try:
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
    finally:
        reset_fleet_table_stream_registry_for_tests()
        reset_inference_table_stream_registry_for_tests()

    by_player: dict[int, set[str]] = {}
    for request in submitted:
        assert request.force_fresh is True
        assert request.priority_band == "stream_attached"
        assert request.submission_open is None
        assert request.scope.turn == 10
        by_player.setdefault(request.scope.player_id, set()).add(request.scope.analytic_id)
    assert set(by_player) == set(player_ids)
    assert all(
        analytics == {FLEET_ANALYTIC_ID, SCORES_ANALYTIC_ID} for analytics in by_player.values()
    )
    assert fleet.wake_multiplex.is_set()
    assert scores.wake_multiplex.is_set()
    for player_id in player_ids:
        assert (
            fleet.scheduled_rows[player_id].session.event_queue.events[0]["type"] == "work_accepted"
        )
        assert (
            scores.scheduled_rows[player_id].session.event_queue.events[0]["type"]
            == "work_accepted"
        )


def test_no_live_stream_does_not_create_an_orchestrator(sample_turn, monkeypatch):
    _host, ctx = context_at_turn(sample_turn, 10)

    def refuse():
        raise AssertionError("orchestrator created")

    monkeypatch.setattr("api.analytics.on_walk_live.get_compute_orchestrator", refuse)
    try:
        submit_on_walks_for_live_streams(ctx.game_id)
        attach_stream(
            get_fleet_table_stream_registry(),
            FleetTableStreamScope(ctx.game_id, ctx.perspective, 10),
            _host,
            None,
            roster_player_ids(_host),
        )
        submit_on_walks_for_live_streams(ctx.game_id)
    finally:
        reset_fleet_table_stream_registry_for_tests()


def test_off_setting_fleet_defers_one_player_until_the_node_is_terminal(sample_turn, monkeypatch):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_ids = roster_player_ids(host)
    assert len(player_ids) >= 2
    blocked = player_ids[0]
    free = player_ids[1]
    attach_stream(
        get_fleet_table_stream_registry(),
        FleetTableStreamScope(ctx.game_id, ctx.perspective, 10),
        host,
        ctx,
        player_ids,
    )
    orchestrator, submitted = recording_orchestrator(monkeypatch)
    blocker = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=9,
        player_id=blocked,
    )
    node = ComputeNodeRun(
        scope=blocker,
        dependency_scopes=(),
        state="running",
        submission_open=SubmissionOpen(open_turn=10, backfill_earlier_turns=False),
    )
    orchestrator.nodes[blocker] = node
    try:
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
        submitted_ids = {request.scope.player_id for request in submitted}
        assert free in submitted_ids
        assert blocked not in submitted_ids

        node.state = "parked"
        orchestrator.observers.notify_scope_outcome(node)
        orchestrator.observers.drain_post_lock_callbacks()
        assert blocked not in {request.scope.player_id for request in submitted}

        node.state = "failed"
        orchestrator.observers.notify_scope_outcome(node)
        orchestrator.observers.drain_post_lock_callbacks()
        assert blocked in {request.scope.player_id for request in submitted}
        blocked_request = next(
            request for request in submitted if request.scope.player_id == blocked
        )
        assert blocked_request.force_fresh is True
        assert blocked_request.priority_band == "stream_attached"
    finally:
        reset_fleet_table_stream_registry_for_tests()


def test_off_setting_scoreboard_defers_until_terminal_then_registers_the_walk(sample_turn):
    """A running off-setting scoreboard does not absorb the on-walk.

    The walk is submitted after that node is terminal, with no entry step, and
    the registered plan includes the prior fleet.
    """
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    attach_stream(
        get_inference_table_stream_registry(),
        InferenceStreamScope(ctx.game_id, ctx.perspective, 10),
        host,
        ctx,
        [player_id],
    )
    orchestrator = held_pool_orchestrator()
    scores_scope = shell_scope(ctx, SCORES_ANALYTIC_ID, 10, player_id)
    node = ComputeNodeRun(
        scope=scores_scope,
        dependency_scopes=(),
        state="running",
        submission_open=SubmissionOpen(open_turn=10, backfill_earlier_turns=False),
    )
    orchestrator.nodes[scores_scope] = node
    prior = shell_scope(ctx, FLEET_ANALYTIC_ID, 9, player_id)
    try:
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
        assert orchestrator.nodes[scores_scope] is node
        assert node.submission_open.backfill_earlier_turns is False
        assert prior not in orchestrator.nodes

        node.state = "parked"
        orchestrator.observers.notify_scope_outcome(node)
        orchestrator.observers.drain_post_lock_callbacks()
        assert prior not in orchestrator.nodes
        assert node.submission_open.backfill_earlier_turns is False

        node.state = "failed"
        orchestrator.observers.notify_scope_outcome(node)
        orchestrator.observers.drain_post_lock_callbacks()
        registered = orchestrator.nodes[scores_scope]
        assert registered is not node
        assert registered.submission_open.backfill_earlier_turns is True
        assert prior in orchestrator.nodes
        assert orchestrator.nodes[prior].submission_open.backfill_earlier_turns is True
    finally:
        reset_inference_table_stream_registry_for_tests()


def test_deferred_on_walk_skips_a_closed_stream_or_a_setting_that_turned_off(
    sample_turn, monkeypatch
):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    scope = FleetTableStreamScope(ctx.game_id, ctx.perspective, 10)
    attach_stream(get_fleet_table_stream_registry(), scope, host, ctx, [player_id])
    orchestrator, submitted = recording_orchestrator(monkeypatch)
    blocker = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=9,
        player_id=player_id,
    )
    node = ComputeNodeRun(
        scope=blocker,
        dependency_scopes=(),
        state="running",
        submission_open=SubmissionOpen(backfill_earlier_turns=False),
    )
    orchestrator.nodes[blocker] = node
    try:
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
        assert player_id not in {request.scope.player_id for request in submitted}
        fleet_persistence(ctx)._storage.put(
            backfill_earlier_turns_store_key(ctx.game_id),
            backfill_earlier_turns_document(False),
        )
        node.state = "complete"
        orchestrator.observers.notify_scope_outcome(node)
        orchestrator.observers.drain_post_lock_callbacks()
        assert player_id not in {request.scope.player_id for request in submitted}
    finally:
        reset_fleet_table_stream_registry_for_tests()

    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    scope = FleetTableStreamScope(ctx.game_id, ctx.perspective, 10)
    attach_stream(get_fleet_table_stream_registry(), scope, host, ctx, [player_id])
    orchestrator, submitted = recording_orchestrator(monkeypatch)
    blocker = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=9,
        player_id=player_id,
    )
    node = ComputeNodeRun(
        scope=blocker,
        dependency_scopes=(),
        state="running",
        submission_open=SubmissionOpen(backfill_earlier_turns=False),
    )
    orchestrator.nodes[blocker] = node
    try:
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
        assert player_id not in {request.scope.player_id for request in submitted}
        reset_fleet_table_stream_registry_for_tests()
        node.state = "failed"
        orchestrator.observers.notify_scope_outcome(node)
        orchestrator.observers.drain_post_lock_callbacks()
        assert player_id not in {request.scope.player_id for request in submitted}
    finally:
        reset_fleet_table_stream_registry_for_tests()

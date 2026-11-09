"""Live on-walk submission: one failing player and one pending waiter per player."""

from __future__ import annotations

import logging
from dataclasses import replace

from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.fleet_table_stream_registry import (
    get_fleet_table_stream_registry,
    reset_fleet_table_stream_registry_for_tests,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.on_walk_live import submit_on_walks_for_live_streams
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.serialization.backfill_earlier_turns import (
    backfill_earlier_turns_document,
    backfill_earlier_turns_store_key,
)

from tests.export_chain_test_fixtures import enable_backfill_earlier_turns
from tests.off_mode_catch_up_helpers import context_at_turn
from tests.on_walk_live_helpers import attach_stream, recording_orchestrator, roster_player_ids
from tests.scores_exports_helpers import first_player_id

_WORK_ACCEPTED = {"type": "work_accepted"}


def _store_backfill(ctx, enabled: bool) -> None:
    ctx.export_services[FLEET_ANALYTIC_ID].persistence._storage.put(
        backfill_earlier_turns_store_key(ctx.game_id),
        backfill_earlier_turns_document(enabled),
    )


def _off_setting_fleet_blocker(orchestrator, ctx, player_id: int) -> ComputeNodeRun:
    scope = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=9,
        player_id=player_id,
    )
    node = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state="running",
        submission_open=SubmissionOpen(open_turn=10, backfill_earlier_turns=False),
    )
    orchestrator.nodes[scope] = node
    return node


def _finish(orchestrator, node: ComputeNodeRun, state: str) -> None:
    node.state = state
    orchestrator.observers.notify_scope_outcome(node)
    orchestrator.observers.drain_post_lock_callbacks()


def _requests_for(submitted: list, player_id: int) -> list:
    return [request for request in submitted if request.scope.player_id == player_id]


def _failing_orchestrator(failing_player_id: int) -> tuple[ComputeOrchestrator, list]:
    orchestrator = ComputeOrchestrator(compute_registry={})
    submitted: list = []

    def submit(request):
        if request.scope.player_id == failing_player_id:
            raise RuntimeError("mark write failed")
        submitted.append(request)

    orchestrator.submit = submit
    return orchestrator, submitted


def _error_records_for(caplog, game_id: int, player_id: int) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.levelno == logging.ERROR
        and f"game {game_id}" in record.getMessage()
        and f"player {player_id}" in record.getMessage()
    ]


def test_one_failing_player_is_logged_and_the_others_still_submit(sample_turn, caplog):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_ids = roster_player_ids(host)
    failing = player_ids[0]
    stream = attach_stream(
        get_fleet_table_stream_registry(),
        FleetTableStreamScope(ctx.game_id, ctx.perspective, 10),
        host,
        ctx,
        player_ids,
    )
    orchestrator, submitted = _failing_orchestrator(failing)
    try:
        with caplog.at_level(logging.ERROR):
            submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
    finally:
        reset_fleet_table_stream_registry_for_tests()

    assert {request.scope.player_id for request in submitted} == set(player_ids[1:])
    assert stream.accepted_events(failing) == []
    for player_id in player_ids[1:]:
        assert stream.accepted_events(player_id) == [_WORK_ACCEPTED]
    assert _error_records_for(caplog, ctx.game_id, failing)


def test_a_failing_deferred_submission_is_logged_and_does_not_escape_the_drain(sample_turn, caplog):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    attach_stream(
        get_fleet_table_stream_registry(),
        FleetTableStreamScope(ctx.game_id, ctx.perspective, 10),
        host,
        ctx,
        [player_id],
    )
    orchestrator, submitted = _failing_orchestrator(player_id)
    node = _off_setting_fleet_blocker(orchestrator, ctx, player_id)
    try:
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
        with caplog.at_level(logging.ERROR):
            _finish(orchestrator, node, "complete")
    finally:
        reset_fleet_table_stream_registry_for_tests()

    assert _requests_for(submitted, player_id) == []
    assert _error_records_for(caplog, ctx.game_id, player_id)


def test_on_off_on_while_blocked_submits_each_shell_once_with_the_latest_stream(
    sample_turn, monkeypatch
):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    registry = get_fleet_table_stream_registry()
    scope = FleetTableStreamScope(ctx.game_id, ctx.perspective, 10)
    first_stream = attach_stream(registry, scope, host, ctx, [player_id])
    orchestrator, submitted = recording_orchestrator(monkeypatch)
    node = _off_setting_fleet_blocker(orchestrator, ctx, player_id)
    latest_ctx = replace(ctx)
    try:
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
        _store_backfill(ctx, False)
        _store_backfill(ctx, True)
        latest_stream = attach_stream(registry, scope, host, latest_ctx, [player_id])
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
        assert _requests_for(submitted, player_id) == []

        _finish(orchestrator, node, "complete")
    finally:
        reset_fleet_table_stream_registry_for_tests()

    blocked_requests = _requests_for(submitted, player_id)
    assert len(blocked_requests) == 1
    assert blocked_requests[0].ctx is latest_ctx
    assert latest_stream.accepted_events(player_id) == [_WORK_ACCEPTED]
    assert first_stream.accepted_events(player_id) == []


def test_a_deduplicated_waiter_skips_when_the_setting_turned_off_and_then_lets_go(
    sample_turn, monkeypatch
):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    attach_stream(
        get_fleet_table_stream_registry(),
        FleetTableStreamScope(ctx.game_id, ctx.perspective, 10),
        host,
        ctx,
        [player_id],
    )
    orchestrator, submitted = recording_orchestrator(monkeypatch)
    first_blocker = _off_setting_fleet_blocker(orchestrator, ctx, player_id)
    try:
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
        _store_backfill(ctx, False)
        _finish(orchestrator, first_blocker, "complete")
        assert _requests_for(submitted, player_id) == []

        _store_backfill(ctx, True)
        second_blocker = _off_setting_fleet_blocker(orchestrator, ctx, player_id)
        before_clear = len(submitted)
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
        assert _requests_for(submitted[before_clear:], player_id) == []
        _finish(orchestrator, second_blocker, "failed")
    finally:
        reset_fleet_table_stream_registry_for_tests()

    assert len(_requests_for(submitted[before_clear:], player_id)) == 1

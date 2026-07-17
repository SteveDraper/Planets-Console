"""Regression: timeline finish/ready gauges must not re-enter orchestrator or pool locks."""

from __future__ import annotations

from unittest.mock import MagicMock

from api.compute.diagnostics.bindings import BoundOrchestrator
from api.compute.diagnostics.concurrency_recorder import ConcurrencyTimelineRecorder
from api.compute.diagnostics.freeze import ShellContextKey
from api.compute.diagnostics.history import ComputeCompletionHistory
from api.compute.orchestrator import ComputeNodeRun
from api.compute.scope import ComputeScope


def _recorder(
    *,
    bound: tuple[BoundOrchestrator, ...] = (),
    global_queue_depth=None,
) -> ConcurrencyTimelineRecorder:
    shell = ShellContextKey(game_id=1, perspective=1, turn=8)
    depth_fn = global_queue_depth if global_queue_depth is not None else (lambda: 0)
    return ConcurrencyTimelineRecorder(
        timeline_capacity=lambda: 64,
        bound_orchestrators=lambda: bound,
        in_flight_records=lambda: (),
        global_queue_depth=depth_fn,
        configured_workers=lambda: 4,
        ancestor_turns=lambda _shell: frozenset({8}),
        history_for_shell=lambda _shell: ComputeCompletionHistory(capacity=16),
        active_shell=lambda: shell,
    )


def _bound_orch(*, orchestrator: MagicMock) -> BoundOrchestrator:
    return BoundOrchestrator(
        orchestrator=orchestrator,
        game_id=1,
        perspective=1,
        ambient_turn=8,
        unregister_dispatch_gate=lambda: None,
        unregister_dispatch_commit_hook=lambda: None,
        unregister_step_complete_listener=lambda: None,
        unregister_ready_listener=lambda: None,
        unregister_ready_queue_listener=lambda: None,
        unregister_inline_start_listener=lambda: None,
        unregister_lifecycle_listener=lambda: None,
    )


def test_record_finish_uses_ready_cache_not_live_orchestrator_snapshot() -> None:
    """Finish listeners run under drain_post_lock; live orch sampling deadlocks."""
    orchestrator = MagicMock()
    orchestrator.diagnostics_snapshot.side_effect = AssertionError(
        "record_finish must not call diagnostics_snapshot"
    )
    orchestrator.pool_registration_id = 1
    recorder = _recorder(bound=(_bound_orch(orchestrator=orchestrator),))
    shell = ShellContextKey(game_id=1, perspective=1, turn=8)
    scope = ComputeScope(
        analytic_id="scores",
        game_id=1,
        perspective=1,
        turn=8,
        player_id=3,
    )
    node = ComputeNodeRun(scope=scope, dependency_scopes=(), step_index=1)

    recorder.record_finish(
        shell,
        scope=scope,
        node=node,
        step_kind="tier_solve",
        step_index=node.step_index,
        surface="pool",
        terminal_state="success",
        orchestrator_id=1,
        backend="thread",
    )

    orchestrator.diagnostics_snapshot.assert_not_called()


def test_record_ready_default_does_not_sample_live_orchestrators() -> None:
    orchestrator = MagicMock()
    orchestrator.diagnostics_snapshot.side_effect = AssertionError(
        "ready record must not call diagnostics_snapshot by default"
    )
    orchestrator.pool_registration_id = 1
    recorder = _recorder(bound=(_bound_orch(orchestrator=orchestrator),))
    shell = ShellContextKey(game_id=1, perspective=1, turn=8)
    scope = ComputeScope(
        analytic_id="scores",
        game_id=1,
        perspective=1,
        turn=8,
        player_id=3,
    )

    recorder.record(
        shell,
        kind="ready",
        scope=scope,
        orchestrator_id=1,
        step_kind="tier_solve",
        step_index=0,
        sample_ready_from_orchestrators=False,
    )

    orchestrator.diagnostics_snapshot.assert_not_called()


def test_listener_gauges_do_not_sample_live_global_queue_depth() -> None:
    """Ready/finish/lifecycle paths must not call into the pool for queue depth.

    Workers hold the pool condition while taking the diagnostics controller lock
    (predicate / on_dequeued). Sampling ``snapshot_work_queue`` from gauges under
    drain is controller→pool and ABBA-deadlocks dequeue.
    """
    depth_calls = 0

    def boom_depth() -> int:
        nonlocal depth_calls
        depth_calls += 1
        raise AssertionError("gauges must not sample live pool queue depth")

    recorder = _recorder(global_queue_depth=boom_depth)
    shell = ShellContextKey(game_id=1, perspective=1, turn=8)
    scope = ComputeScope(
        analytic_id="fleet",
        game_id=1,
        perspective=1,
        turn=8,
        player_id=3,
    )
    node = ComputeNodeRun(scope=scope, dependency_scopes=(), step_index=0)

    recorder.record(
        shell,
        kind="ready",
        scope=scope,
        orchestrator_id=1,
        step_kind="materialize",
        step_index=0,
    )
    recorder.record(
        shell,
        kind="inline_start",
        scope=scope,
        orchestrator_id=1,
        step_kind="materialize",
        step_index=0,
    )
    recorder.record_finish(
        shell,
        scope=scope,
        node=node,
        step_kind="materialize",
        step_index=0,
        surface="inline",
        terminal_state="success",
        orchestrator_id=1,
        backend="thread",
    )
    recorder.record_lifecycle(
        shell,
        kind="abort",
        scope=scope,
        orchestrator_id=1,
        step_kind="materialize",
        step_index=0,
    )

    assert depth_calls == 0


def test_explicit_global_queue_depth_updates_last_known() -> None:
    recorder = _recorder(global_queue_depth=lambda: 99)
    shell = ShellContextKey(game_id=1, perspective=1, turn=8)
    scope = ComputeScope(
        analytic_id="fleet",
        game_id=1,
        perspective=1,
        turn=8,
        player_id=3,
    )

    recorder.record(
        shell,
        kind="enqueue",
        scope=scope,
        orchestrator_id=1,
        step_kind="materialize",
        step_index=0,
        global_queue_depth=3,
    )
    recorder.record(
        shell,
        kind="ready",
        scope=scope,
        orchestrator_id=1,
        step_kind="materialize",
        step_index=0,
    )

    events = recorder.recent(shell)
    assert events[-2].gauges.global_queue_depth == 3
    assert events[-1].gauges.global_queue_depth == 3

"""Synthetic harness planting A/B/C/D concurrency timeline signatures (#230).

These tests assert timeline/rollup *shapes* an operator would use to classify
bottlenecks. They do not auto-label a bottleneck class.
"""

from __future__ import annotations

import time

import pytest
from api.analytics.catalog import TurnAnalyticCatalogEntry
from api.analytics.export_types import ExportScope
from api.analytics.exports.catalog import AnalyticExportCatalog
from api.analytics.exports.registry import merge_export_registry
from api.analytics.registration import TurnAnalyticRegistration
from api.compute import (
    AnalyticComputeProfile,
    ComputeOrchestrator,
    ComputeRequest,
    ComputeStepSpec,
    ScopeKeySpec,
    build_compute_registry,
    normalize_export_scope_to_compute_scope,
    reset_compute_worker_pool_for_tests,
)
from api.compute.diagnostics import (
    ShellContextKey,
    get_compute_diagnostics_controller,
    reset_compute_diagnostics_for_tests,
    snapshot_to_wire,
)
from api.compute.diagnostics.rollup import build_concurrency_timeline_rollup, rollup_to_wire
from api.compute.diagnostics.timeline import (
    OccupancyGauges,
    make_concurrency_event,
)
from api.compute.runtime import reset_orchestrators_for_tests
from api.compute.scope import format_compute_scope_key
from api.compute.wire import StepResult
from api.config import ApiConfig, set_config

from tests.fixtures.export_framework.harness import make_fixture_query_context
from tests.test_compute_foundation import _StubPersistencePolicy


@pytest.fixture(autouse=True)
def _reset_state():
    reset_compute_diagnostics_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=True))
    yield
    reset_compute_diagnostics_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=False))


def _gauges(
    *,
    ready: int = 0,
    scoped_if: int = 0,
    global_if: int = 0,
    queue: int = 0,
    workers: int = 4,
) -> OccupancyGauges:
    return OccupancyGauges(
        scoped_ready_depth=ready,
        scoped_in_flight_count=scoped_if,
        global_in_flight_count=global_if,
        global_queue_depth=queue,
        configured_workers=workers,
    )


def _plant(
    *,
    kind: str,
    player: int,
    backend: str | None,
    gauges: OccupancyGauges,
    duration_ms: float | None = None,
    analytic: str = "scores",
) -> object:
    scope_key = f"{analytic}@g1@p1@t8@pl{player}"
    return make_concurrency_event(
        kind=kind,  # type: ignore[arg-type]
        scope_key=scope_key,
        execution_key=f"{scope_key}|{kind}|{player}",
        gauges=gauges,
        step_kind="materialize",
        step_index=0,
        priority_band="background",
        backend=backend,
        duration_ms=duration_ms,
        terminal_state="success" if kind in {"complete", "inline_complete"} else None,
    )


def test_planted_signature_a_serial_ready_set():
    """Class A: ready/in-flight depth stay ~1 across the timeline."""
    events = tuple(
        _plant(
            kind=kind,
            player=3,
            backend="inline",
            gauges=_gauges(ready=ready, scoped_if=scoped_if, global_if=scoped_if, workers=4),
            duration_ms=5.0 if kind == "inline_complete" else None,
        )
        for kind, ready, scoped_if in (
            ("ready", 1, 0),
            ("inline_start", 0, 1),
            ("inline_complete", 0, 0),
            ("ready", 1, 0),
            ("inline_start", 0, 1),
            ("inline_complete", 0, 0),
        )
    )
    rollup = build_concurrency_timeline_rollup(events)  # type: ignore[arg-type]
    assert rollup.max_scoped_ready_depth <= 1
    assert rollup.max_scoped_in_flight <= 1
    assert rollup.unique_players == (3,)
    assert "bottleneckClass" not in rollup_to_wire(rollup)


def test_planted_signature_b_dispatch_starvation():
    """Class B: deep ready set while scoped in-flight stays near zero."""
    events = tuple(
        _plant(
            kind="ready",
            player=player,
            backend="thread",
            gauges=_gauges(ready=ready, scoped_if=0, global_if=global_if, queue=ready, workers=4),
        )
        for player, ready, global_if in (
            (1, 1, 4),
            (2, 2, 4),
            (3, 3, 4),
            (4, 5, 4),
            (5, 6, 4),
        )
    )
    rollup = build_concurrency_timeline_rollup(events)  # type: ignore[arg-type]
    assert rollup.max_scoped_ready_depth >= 5
    assert rollup.max_scoped_in_flight == 0
    assert rollup.max_global_in_flight >= 4
    assert rollup.configured_workers == 4


def test_planted_signature_c_backend_gil_ceiling():
    """Class C: multiple in-flight with thread/interpreter backends and durations."""
    events = tuple(
        _plant(
            kind=kind,
            player=3,
            backend=backend,
            gauges=_gauges(ready=0, scoped_if=scoped_if, global_if=scoped_if, workers=4),
            duration_ms=duration,
        )
        for kind, backend, scoped_if, duration in (
            ("start", "thread", 2, None),
            ("start", "thread", 3, None),
            ("complete", "thread", 2, 40.0),
            ("start", "interpreter", 3, None),
            ("complete", "interpreter", 2, 55.0),
            ("complete", "thread", 1, 38.0),
        )
    )
    rollup = build_concurrency_timeline_rollup(events)  # type: ignore[arg-type]
    assert rollup.max_scoped_in_flight >= 2
    assert set(rollup.backend_histogram) <= {"thread", "interpreter"}
    assert "thread" in rollup.duration_by_backend_ms
    assert rollup.duration_by_backend_ms["thread"]["max"] is not None


def test_planted_signature_d_scope_under_submission():
    """Class D: many events but only one unique player appears."""
    events = tuple(
        _plant(
            kind=kind,
            player=11,
            backend="thread",
            gauges=_gauges(ready=1, scoped_if=1, global_if=1, workers=4),
            duration_ms=12.0 if kind == "complete" else None,
            analytic=analytic,
        )
        for kind, analytic in (
            ("ready", "fleet"),
            ("enqueue", "fleet"),
            ("start", "fleet"),
            ("complete", "fleet"),
            ("ready", "scores"),
            ("enqueue", "scores"),
            ("start", "scores"),
            ("complete", "scores"),
        )
    )
    rollup = build_concurrency_timeline_rollup(events)  # type: ignore[arg-type]
    assert rollup.event_count == 8
    assert rollup.unique_players == (11,)


def _probe_export_catalog() -> AnalyticExportCatalog:
    """Non-empty export catalog so DAG planning does not skip the analytic."""
    return AnalyticExportCatalog(
        analytic_id="probe",
        is_ensure_satisfied=lambda _ctx, _scope: False,
    )


def _probe_registration(
    *,
    backend: str,
    delay_s: float = 0.0,
) -> TurnAnalyticRegistration:
    def run_materialize(job: object) -> object:
        if delay_s > 0:
            time.sleep(delay_s)
        return StepResult(outcome="complete", payload={"ok": True, "job": job})

    return TurnAnalyticRegistration(
        catalog_entry=TurnAnalyticCatalogEntry(
            id="probe",
            name="probe",
            supports_table=True,
            supports_map=False,
            type="selectable",
        ),
        compute=lambda _ctx: {"analyticId": "probe"},
        export_catalog=_probe_export_catalog(),
        scope_key_spec=ScopeKeySpec(axes=("perspective", "turn", "player_id")),
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend=backend),),  # type: ignore[arg-type]
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": format_compute_scope_key(scope)}),
        ),
        run_steps=(("materialize", run_materialize),),
    )


def _submit_probe_players(orchestrator, compute_registry, ctx, sample_turn, player_ids):
    handles = []
    for player_id in player_ids:
        scope = normalize_export_scope_to_compute_scope(
            ExportScope(
                game_id=ctx.game_id,
                perspective=ctx.perspective,
                turn=ctx.ambient_turn,
                player_id=player_id,
            ),
            analytic_id="probe",
            scope_key_spec=compute_registry["probe"].scope_key_spec,
        )
        handles.append(
            orchestrator.submit(
                ComputeRequest(ctx=ctx, scope=scope, step_kind="materialize", force_fresh=True),
            )
        )
    return handles


def test_orchestrator_serial_inline_plants_class_a_shape(sample_turn):
    """Real inline chain: timeline never shows deep ready/in-flight concurrency."""
    compute_registry = build_compute_registry((_probe_registration(backend="inline"),))
    ctx = make_fixture_query_context(
        sample_turn,
        registry=merge_export_registry(_probe_export_catalog()),
    )
    pool = reset_compute_worker_pool_for_tests(worker_count=0)
    orchestrator = ComputeOrchestrator(
        compute_registry=compute_registry,
        worker_pool=pool,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
    )
    controller.on_shell_context(shell)
    player_id = sample_turn.scores[0].ownerid
    for _ in range(3):
        handles = _submit_probe_players(
            orchestrator,
            compute_registry,
            ctx,
            sample_turn,
            [player_id],
        )
        assert handles[0].state == "complete"

    wire = snapshot_to_wire(controller.snapshot(shell))
    events = wire["concurrencyTimeline"]
    assert any(event["kind"] == "ready" for event in events)
    assert any(event["kind"] == "inline_complete" for event in events)
    rollup = wire["concurrencyRollup"]
    assert rollup["maxScopedReadyDepth"] <= 1
    assert rollup["maxScopedInFlight"] <= 1
    assert rollup["uniquePlayers"] == [player_id]
    assert "bottleneckClass" not in rollup


def test_orchestrator_freeze_holds_ready_set_plants_class_b_shape(sample_turn):
    """Frozen dispatch with multiple ready players: deep ready, zero scoped in-flight."""
    compute_registry = build_compute_registry((_probe_registration(backend="thread"),))
    ctx = make_fixture_query_context(
        sample_turn,
        registry=merge_export_registry(_probe_export_catalog()),
    )
    pool = reset_compute_worker_pool_for_tests(worker_count=2)
    orchestrator = ComputeOrchestrator(
        compute_registry=compute_registry,
        worker_pool=pool,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
    )
    controller.on_shell_context(shell)
    controller.set_freeze_armed(shell, freeze_armed=True)

    player_ids = [score.ownerid for score in sample_turn.scores[:3]]
    _submit_probe_players(orchestrator, compute_registry, ctx, sample_turn, player_ids)

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        wire = snapshot_to_wire(controller.snapshot(shell))
        if wire["liveOccupancy"]["scopedReadyDepth"] >= 2:
            break
        time.sleep(0.01)
    else:
        pytest.fail(
            f"expected frozen ready depth >= 2; got "
            f"{snapshot_to_wire(controller.snapshot(shell))['liveOccupancy']}"
        )

    wire = snapshot_to_wire(controller.snapshot(shell))
    assert wire["liveOccupancy"]["scopedInFlightCount"] == 0
    assert wire["liveOccupancy"]["scopedReadyDepth"] >= 2
    kinds = {event["kind"] for event in wire["concurrencyTimeline"]}
    assert "ready" in kinds
    assert "start" not in kinds
    rollup = wire["concurrencyRollup"]
    assert rollup["maxScopedReadyDepth"] >= 2
    assert rollup["maxScopedInFlight"] == 0
    assert len(rollup["uniquePlayers"]) >= 2


def test_orchestrator_parallel_thread_plants_class_c_in_flight(sample_turn):
    """Multiple thread workers in flight: scoped in-flight can exceed 1."""
    compute_registry = build_compute_registry(
        (_probe_registration(backend="thread", delay_s=0.15),)
    )
    ctx = make_fixture_query_context(
        sample_turn,
        registry=merge_export_registry(_probe_export_catalog()),
    )
    pool = reset_compute_worker_pool_for_tests(worker_count=3)
    orchestrator = ComputeOrchestrator(
        compute_registry=compute_registry,
        worker_pool=pool,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
    )
    controller.on_shell_context(shell)

    player_ids = [score.ownerid for score in sample_turn.scores[:3]]
    handles = _submit_probe_players(
        orchestrator,
        compute_registry,
        ctx,
        sample_turn,
        player_ids,
    )

    saw_parallel = False
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        wire = snapshot_to_wire(controller.snapshot(shell))
        if wire["liveOccupancy"]["scopedInFlightCount"] >= 2:
            saw_parallel = True
            break
        if all(handle.state in {"complete", "failed"} for handle in handles):
            break
        time.sleep(0.01)

    for handle in handles:
        deadline = time.monotonic() + 2.0
        while handle.state not in {"complete", "failed"} and time.monotonic() < deadline:
            time.sleep(0.01)
        assert handle.state == "complete"

    wire = snapshot_to_wire(controller.snapshot(shell))
    kinds = {event["kind"] for event in wire["concurrencyTimeline"]}
    assert "enqueue" in kinds
    assert "start" in kinds
    assert "complete" in kinds
    assert saw_parallel or wire["concurrencyRollup"]["maxScopedInFlight"] >= 2
    assert wire["concurrencyRollup"]["backendHistogram"].get("thread", 0) >= 1


def test_fail_from_ready_does_not_inflate_enqueue_ready_depth(sample_turn):
    """Aborting a ready node must not leave sticky ready-depth overcount on enqueue.

    The old ±1 shadow counter only decremented on enqueue/inline_start, so
    fail-from-ready drifted high and pool-lock enqueue gauges stayed inflated.
    """
    compute_registry = build_compute_registry((_probe_registration(backend="thread"),))
    ctx = make_fixture_query_context(
        sample_turn,
        registry=merge_export_registry(_probe_export_catalog()),
    )
    pool = reset_compute_worker_pool_for_tests(worker_count=2)
    orchestrator = ComputeOrchestrator(
        compute_registry=compute_registry,
        worker_pool=pool,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=ctx.ambient_turn,
    )
    controller.on_shell_context(shell)
    controller.set_freeze_armed(shell, freeze_armed=True)

    player_ids = [score.ownerid for score in sample_turn.scores[:2]]
    handles = _submit_probe_players(
        orchestrator,
        compute_registry,
        ctx,
        sample_turn,
        player_ids,
    )
    assert all(handle.state == "ready" for handle in handles)
    assert len(orchestrator.ready_scopes()) == 2

    aborted = handles[0].scope
    assert orchestrator.abort_scope(aborted, RuntimeError("fail-from-ready")) is True
    assert orchestrator.nodes[aborted].state == "failed"
    assert len(orchestrator.ready_scopes()) == 1

    controller.set_freeze_armed(shell, freeze_armed=False)

    remaining = handles[1]
    deadline = time.monotonic() + 2.0
    while remaining.state not in {"complete", "failed"} and time.monotonic() < deadline:
        time.sleep(0.01)
    assert remaining.state == "complete"

    wire = snapshot_to_wire(controller.snapshot(shell))
    enqueue_events = [event for event in wire["concurrencyTimeline"] if event["kind"] == "enqueue"]
    assert enqueue_events, "expected pool enqueue after disarm"
    # After fail-from-ready left one ready node, dispatching it must record depth 0
    # on enqueue (node already left ready under the orch lock before pool submit).
    assert enqueue_events[-1]["gauges"]["scopedReadyDepth"] == 0
    assert wire["concurrencyRollup"]["maxScopedReadyDepth"] <= 2


def test_ready_to_waiting_deps_notifies_ready_queue_depth(sample_turn):
    """Dispatch dropping a stale ready entry to waiting_deps must notify depth listeners."""
    compute_registry = build_compute_registry((_probe_registration(backend="thread"),))
    ctx = make_fixture_query_context(
        sample_turn,
        registry=merge_export_registry(_probe_export_catalog()),
    )
    orchestrator = ComputeOrchestrator(
        compute_registry=compute_registry,
        pool_submitter=lambda _node, _step: None,
    )
    snapshots: list[tuple] = []
    orchestrator.register_ready_queue_listener(lambda scopes: snapshots.append(scopes))

    player_id = sample_turn.scores[0].ownerid
    scope = normalize_export_scope_to_compute_scope(
        ExportScope(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=ctx.ambient_turn,
            player_id=player_id,
        ),
        analytic_id="probe",
        scope_key_spec=compute_registry["probe"].scope_key_spec,
    )
    # No dependencies: plant a ready-queue entry whose deps are incomplete by
    # pointing at a missing dependency scope, then dispatch.
    missing_dep = normalize_export_scope_to_compute_scope(
        ExportScope(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=ctx.ambient_turn,
            player_id=player_id + 10_000,
        ),
        analytic_id="probe",
        scope_key_spec=compute_registry["probe"].scope_key_spec,
    )
    with orchestrator._condition:
        from api.compute.orchestrator import ComputeNodeRun

        node = ComputeNodeRun(
            scope=scope,
            dependency_scopes=(missing_dep,),
            state="ready",
        )
        orchestrator._nodes[scope] = node
        orchestrator._ready_queue.append(scope)
        snapshots.clear()
        pending_inline, pending_pool = orchestrator._dispatch()

    assert pending_inline == ()
    assert pending_pool == ()
    assert node.state == "waiting_deps"
    assert orchestrator.ready_scopes() == ()
    assert snapshots, "expected ready-queue-changed after waiting_deps drop"
    assert snapshots[-1] == ()

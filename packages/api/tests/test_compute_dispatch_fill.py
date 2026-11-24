"""A dispatch pass commits every dispatchable ready step.

Ready work waits in the ready queue only while a dispatch gate or commit
hook holds it. A transition that schedules no dispatch pass (a park, a
persist-deferred demotion whose recovery submit fails, an item dropped at
its pick) therefore leaves no ready work behind, and a gate release commits
the whole backlog it releases in one pass.
"""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import replace

import pytest
from api.analytics.export_types import ExportScope
from api.compute import (
    ComputeHandle,
    ComputeOrchestrator,
    ComputeRequest,
    ComputeScope,
    build_compute_registry,
)
from api.compute.diagnostics import (
    ShellContextKey,
    get_compute_diagnostics_controller,
    reset_compute_diagnostics_for_tests,
)
from api.compute.errors import ComputeRequesterEndedError, ComputeWaitTimeoutError
from api.compute.pools import ComputeWorkerPool
from api.compute.wire import StepResult
from api.config import ApiConfig, set_config

from tests.compute_orchestrator_fixtures import (
    RecordingPoolSubmitter,
    make_compute_scope,
    make_export_scope,
    pool_compute_registration,
)
from tests.compute_persist_deferred_helpers import (
    persist_branch_step_deferred,
    running_branch,
    shared_recovery,
)
from tests.compute_pool_test_helpers import complete_running_pool_step
from tests.fixtures.export_framework.diamond_exports import SHARED_ID
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    make_fixture_query_context,
)


@pytest.fixture(autouse=True)
def _compute_diagnostics_enabled():
    reset_compute_diagnostics_for_tests()
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=True))
    yield
    reset_compute_diagnostics_for_tests()
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=False))


def _ctx(sample_turn):
    return make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)


def _player_scopes(sample_turn) -> tuple[ComputeScope, ...]:
    """One SHARED scope per player of the sample turn, in the context's shell."""
    ctx = _ctx(sample_turn)
    return tuple(
        make_compute_scope(
            SHARED_ID,
            ExportScope(
                game_id=ctx.game_id,
                perspective=ctx.perspective,
                turn=ctx.ambient_turn,
                player_id=row.ownerid,
            ),
        )
        for row in sample_turn.scores
    )


def _perspective_scopes(sample_turn, perspectives: tuple[int, ...]) -> tuple[ComputeScope, ...]:
    export_scope = make_export_scope(sample_turn)
    return tuple(
        make_compute_scope(SHARED_ID, replace(export_scope, perspective=perspective))
        for perspective in perspectives
    )


def _pool_orchestrator(pool_submitter) -> ComputeOrchestrator:
    return ComputeOrchestrator(
        compute_registry=build_compute_registry(
            (pool_compute_registration(SHARED_ID, backend="thread"),)
        ),
        pool_submitter=pool_submitter,
    )


def _submit_held_then_dispatch(
    orchestrator: ComputeOrchestrator, ctx, scopes
) -> tuple[ComputeHandle, ...]:
    """Submit ``scopes`` behind a gate, lift it, and run exactly one dispatch pass."""
    release = orchestrator.observers.register_dispatch_gate(lambda _node: False)
    handles = tuple(orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope)) for scope in scopes)
    release()
    orchestrator.dispatch_ready_work()
    return handles


def test_one_pass_commits_every_ready_pool_step(sample_turn):
    scopes = _player_scopes(sample_turn)
    assert len(scopes) > 2
    submitter = RecordingPoolSubmitter()
    orchestrator = _pool_orchestrator(submitter)

    _submit_held_then_dispatch(orchestrator, _ctx(sample_turn), scopes)

    assert [scope for scope, _kind in submitter.submissions] == list(scopes)
    assert all(orchestrator.nodes[scope].state == "running" for scope in scopes)
    assert orchestrator.ready_scopes() == ()


# The park, drop-at-pick and demotion tests below pin that nothing ready is
# left behind across each transition. Their setup pass already commits every
# step, so they hold with the one-pass rule rather than test a pass the
# transition schedules (none does).


def test_a_park_leaves_no_ready_pool_step_behind(sample_turn):
    parked, other = _perspective_scopes(sample_turn, (1, 2))
    submitter = RecordingPoolSubmitter()
    orchestrator = _pool_orchestrator(submitter)
    _submit_held_then_dispatch(orchestrator, _ctx(sample_turn), (parked, other))

    complete_running_pool_step(orchestrator, parked, result_wire=StepResult(outcome="park"))

    assert orchestrator.nodes[parked].state == "parked"
    assert orchestrator.nodes[other].state == "running"
    assert orchestrator.ready_scopes() == ()


def test_an_item_dropped_at_its_pick_leaves_no_ready_pool_step_behind(sample_turn):
    dropped, *others = _perspective_scopes(sample_turn, (1, 2, 3))
    pool = ComputeWorkerPool(worker_count=0)
    try:
        orchestrator = ComputeOrchestrator(
            compute_registry=build_compute_registry(
                (pool_compute_registration(SHARED_ID, backend="thread"),)
            ),
            worker_pool=pool,
        )
        _submit_held_then_dispatch(orchestrator, _ctx(sample_turn), (dropped, *others))
        assert len(pool.snapshot_work_queue()) == 3
        assert orchestrator.abort_scope(dropped, RuntimeError("aborted while queued"))

        picked = pool.take_next_item_for_tests()
        assert picked is not None
        assert picked.item.scope == dropped
        pool._execute_item(picked)

        assert [queued.item.scope for queued in pool.snapshot_work_queue()] == others
        assert orchestrator.ready_scopes() == ()
    finally:
        pool.shutdown()


@pytest.mark.allows_post_lock_callback_errors
def test_a_demotion_whose_recovery_submit_is_refused_leaves_no_ready_pool_step_behind(
    sample_turn, monkeypatch
):
    setup = running_branch(sample_turn)
    orchestrator = setup.orchestrator
    others = _perspective_scopes(sample_turn, (2, 3))
    _submit_held_then_dispatch(orchestrator, setup.ctx, others)
    submit = orchestrator.submit

    def refuse_the_recovery(request: ComputeRequest):
        if request.scope == setup.shared:
            assert request.requester is not None
            raise ComputeRequesterEndedError(request.requester)
        return submit(request)

    monkeypatch.setattr(orchestrator, "submit", refuse_the_recovery)

    persist_branch_step_deferred(setup, shared_recovery(setup))

    assert orchestrator.nodes[setup.branch].state == "waiting_deps"
    assert all(orchestrator.nodes[scope].state == "running" for scope in others)
    assert orchestrator.ready_scopes() == ()


def test_a_pass_asks_each_gate_once_per_ready_node(sample_turn):
    held, *admitted = _perspective_scopes(sample_turn, (1, 2, 3, 4))
    submitter = RecordingPoolSubmitter()
    orchestrator = _pool_orchestrator(submitter)
    ctx = _ctx(sample_turn)
    release = orchestrator.observers.register_dispatch_gate(lambda _node: False)
    for scope in (held, *admitted):
        orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    release()
    asked: Counter[ComputeScope] = Counter()

    def hold_one(node) -> bool:
        asked[node.scope] += 1
        return node.scope != held

    orchestrator.observers.register_dispatch_gate(hold_one)

    orchestrator.dispatch_ready_work()

    assert [scope for scope, _kind in submitter.submissions] == admitted
    assert orchestrator.ready_scopes() == (held,)
    assert asked == Counter(dict.fromkeys((held, *admitted), 1))


def test_an_ensure_batch_commits_every_pool_root_in_its_first_pass(sample_turn, monkeypatch):
    scopes = _perspective_scopes(sample_turn, (1, 2, 3))
    submitter = RecordingPoolSubmitter()
    orchestrator = _pool_orchestrator(submitter)
    ctx = _ctx(sample_turn)
    committed_per_pass: list[int] = []
    run_pass = orchestrator.dispatch_ready_work

    def record_committed_by_each_pass() -> None:
        before = len(submitter.submissions)
        run_pass()
        committed_per_pass.append(len(submitter.submissions) - before)

    monkeypatch.setattr(orchestrator, "dispatch_ready_work", record_committed_by_each_pass)

    with pytest.raises(ComputeWaitTimeoutError):
        orchestrator.ensure_scopes(
            tuple(ComputeRequest(ctx=ctx, scope=scope) for scope in scopes),
            timeout=0.01,
        )

    assert committed_per_pass[0] == len(scopes)
    assert {scope for scope, _kind in submitter.submissions} == set(scopes)
    assert all(orchestrator.nodes[scope].state == "running" for scope in scopes)


_PROBE_TIMEOUT_SEC = 5.0


class _ConcurrencyProbe:
    """A blocking pool ``run_step`` that records how many runs overlap.

    Each run waits for ``release``; ``filled`` is set once ``expected`` runs
    are in progress at the same time.
    """

    def __init__(self, expected: int) -> None:
        self._lock = threading.Lock()
        self._expected = expected
        self._running = 0
        self.peak = 0
        self.filled = threading.Event()
        self.release = threading.Event()

    def run_step(self, job: dict[str, str]) -> dict[str, str]:
        with self._lock:
            self._running += 1
            self.peak = max(self.peak, self._running)
            if self._running == self._expected:
                self.filled.set()
        try:
            self.release.wait(timeout=_PROBE_TIMEOUT_SEC)
            return {"result": job["scope"]}
        finally:
            with self._lock:
                self._running -= 1


def test_one_pass_fills_every_free_pool_worker(sample_turn):
    scopes = _perspective_scopes(sample_turn, (1, 2, 3, 4))
    worker_count = 2
    probe = _ConcurrencyProbe(expected=worker_count)
    registration = replace(
        pool_compute_registration(SHARED_ID, backend="thread"),
        run_steps=(("materialize", probe.run_step),),
    )
    pool = ComputeWorkerPool(worker_count=worker_count)
    try:
        orchestrator = ComputeOrchestrator(
            compute_registry=build_compute_registry((registration,)),
            worker_pool=pool,
        )

        handles = _submit_held_then_dispatch(orchestrator, _ctx(sample_turn), scopes)

        # Nothing completes while the probe holds its runs, so no later pass
        # can commit the second step: only the release pass fills both workers.
        assert probe.filled.wait(timeout=_PROBE_TIMEOUT_SEC)
        probe.release.set()
        for handle in handles:
            handle.wait(timeout=_PROBE_TIMEOUT_SEC)
        assert all(orchestrator.nodes[scope].state == "complete" for scope in scopes)
        assert probe.peak == worker_count
    finally:
        probe.release.set()
        pool.shutdown()


def _bound_backlog(sample_turn):
    """A diagnostics-bound pool orchestrator with one frozen ready node per player."""
    ctx = _ctx(sample_turn)
    built_wires: list[ComputeScope] = []
    registration = replace(
        pool_compute_registration(SHARED_ID, backend="thread"),
        build_step_job_wires=(
            (
                "materialize",
                lambda scope, **_kwargs: built_wires.append(scope) or {"scope": SHARED_ID},
            ),
        ),
    )
    submitter = RecordingPoolSubmitter()
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry((registration,)),
        pool_submitter=submitter,
    )
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(orchestrator, ctx)
    shell = ShellContextKey(game_id=ctx.game_id, perspective=ctx.perspective, turn=ctx.ambient_turn)
    controller.set_freeze_armed(shell, freeze_armed=True)
    scopes = _player_scopes(sample_turn)
    for scope in scopes:
        orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))
    assert submitter.submissions == []
    assert set(orchestrator.ready_scopes()) == set(scopes)
    return controller, orchestrator, shell, scopes, submitter, built_wires


def test_disarming_freeze_commits_the_whole_backlog_in_one_pass_and_builds_no_wire(sample_turn):
    controller, orchestrator, shell, scopes, submitter, built_wires = _bound_backlog(sample_turn)

    controller.set_freeze_armed(shell, freeze_armed=False)

    assert {scope for scope, _kind in submitter.submissions} == set(scopes)
    assert orchestrator.ready_scopes() == ()
    assert built_wires == []


def test_a_shell_change_that_moves_the_backlog_out_of_scope_commits_it_in_one_pass(sample_turn):
    controller, orchestrator, shell, scopes, submitter, _built = _bound_backlog(sample_turn)

    controller.on_shell_context(replace(shell, perspective=shell.perspective + 1))

    assert {scope for scope, _kind in submitter.submissions} == set(scopes)
    assert orchestrator.ready_scopes() == ()

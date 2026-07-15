"""Tests for process-wide compute scope lease (#222)."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from api.analytics.catalog import TurnAnalyticCatalogEntry
from api.analytics.export_types import ExportScope
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.registration import TurnAnalyticRegistration
from api.compute import (
    AnalyticComputeProfile,
    ComputeOrchestrator,
    ComputeRequest,
    ComputeScope,
    ComputeStepSpec,
    ScopeKeySpec,
    build_compute_registry,
    normalize_export_scope_to_compute_scope,
)
from api.compute.orchestrator import ComputeNodeRun
from api.compute.scope_lease import (
    ScopeStepClaimKey,
    get_process_scope_lease,
    reset_process_scope_lease_for_tests,
)
from api.compute.scope_terminal_fanout import (
    notify_process_scope_terminal,
    register_process_scope_terminal_listener,
    reset_process_scope_terminal_fanout_for_tests,
)
from api.compute.wire import StepResult

from tests.fixtures.export_framework.diamond_exports import SHARED_ID
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    first_player_id,
    make_fixture_query_context,
)
from tests.test_compute_foundation import _StubPersistencePolicy

_ROW_SCOPE_KEY = ScopeKeySpec(axes=("perspective", "turn", "player_id"))


@pytest.fixture(autouse=True)
def _reset_lease_state():
    reset_process_scope_lease_for_tests()
    reset_process_scope_terminal_fanout_for_tests()
    yield
    reset_process_scope_lease_for_tests()
    reset_process_scope_terminal_fanout_for_tests()


def _catalog_entry(analytic_id: str) -> TurnAnalyticCatalogEntry:
    return TurnAnalyticCatalogEntry(
        id=analytic_id,
        name=analytic_id,
        supports_table=True,
        supports_map=False,
        type="selectable",
    )


def _export_scope(sample_turn) -> ExportScope:
    return ExportScope(
        game_id=sample_turn.game.id,
        perspective=1,
        turn=sample_turn.settings.turn,
        player_id=first_player_id(sample_turn),
    )


def _shared_scope(sample_turn) -> ComputeScope:
    return normalize_export_scope_to_compute_scope(
        _export_scope(sample_turn),
        analytic_id=SHARED_ID,
        scope_key_spec=_ROW_SCOPE_KEY,
    )


class _SatisfiedAfterPersistPolicy(_StubPersistencePolicy):
    def __init__(self) -> None:
        self.satisfied = False
        self.persist_calls = 0
        self.expensive_runs = 0

    def is_satisfied(self, _ctx, _scope) -> bool:
        return self.satisfied

    def persist(self, _ctx, _scope, _result_wire) -> None:
        self.persist_calls += 1
        self.satisfied = True


def _build_wire_with_owner(owner: str):
    def build(scope, **_kwargs):
        return {"scope": scope.analytic_id, "owner": owner}

    return build


def test_scope_lease_try_acquire_parks_second_claimant() -> None:
    lease = get_process_scope_lease()
    scope = ComputeScope(
        analytic_id="a",
        game_id=1,
        perspective=1,
        turn=1,
        player_id=1,
    )
    key = ScopeStepClaimKey(scope=scope, step_kind="materialize")
    wakes: list[str] = []
    assert (
        lease.try_acquire(
            key,
            orchestrator_id=1,
            priority_band="background",
            on_wake=lambda: wakes.append("a"),
        )
        == "acquired"
    )
    assert (
        lease.try_acquire(
            key,
            orchestrator_id=2,
            priority_band="stream_attached",
            on_wake=lambda: wakes.append("b"),
        )
        == "parked"
    )
    callbacks = lease.release(key, orchestrator_id=1)
    assert len(callbacks) == 1
    callbacks[0]()
    assert wakes == ["b"]


def test_scope_lease_distinguishes_step_kind() -> None:
    lease = get_process_scope_lease()
    scope = ComputeScope(
        analytic_id="a",
        game_id=1,
        perspective=1,
        turn=1,
        player_id=1,
    )
    materialize = ScopeStepClaimKey(scope=scope, step_kind="materialize")
    tier_solve = ScopeStepClaimKey(scope=scope, step_kind="tier_solve")
    assert (
        lease.try_acquire(
            materialize,
            orchestrator_id=1,
            priority_band="background",
            on_wake=lambda: None,
        )
        == "acquired"
    )
    assert (
        lease.try_acquire(
            tier_solve,
            orchestrator_id=2,
            priority_band="stream_attached",
            on_wake=lambda: None,
        )
        == "acquired"
    )


def test_two_orchestrators_only_one_runs_expensive_work(sample_turn) -> None:
    persistence = _SatisfiedAfterPersistPolicy()
    started = threading.Event()
    release = threading.Event()

    def run_step(_job: dict[str, Any]) -> StepResult:
        persistence.expensive_runs += 1
        started.set()
        assert release.wait(timeout=5)
        return StepResult(outcome="persist", payload={"ok": True})

    registration = TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(SHARED_ID),
        compute=lambda _ctx: {"analyticId": SHARED_ID},
        export_catalog=empty_export_catalog_for(SHARED_ID),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
        ),
        persistence_policy=persistence,
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(("materialize", run_step),),
    )
    registry = build_compute_registry((registration,))
    ctx_a = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    ctx_b = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    orch_a = ComputeOrchestrator(ctx_a, compute_registry=registry)
    orch_b = ComputeOrchestrator(ctx_b, compute_registry=registry)
    scope = _shared_scope(sample_turn)

    handle_a = None
    error: list[BaseException] = []

    def run_leader() -> None:
        nonlocal handle_a
        try:
            handle_a = orch_a.submit(
                ComputeRequest(scope=scope, priority_band="background"),
            )
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    leader_thread = threading.Thread(target=run_leader)
    leader_thread.start()
    assert started.wait(timeout=5)

    handle_b = orch_b.submit(
        ComputeRequest(scope=scope, priority_band="stream_attached"),
    )
    assert orch_b.nodes[scope].state == "parked"
    assert orch_b.metrics.lease_parks == 1
    assert persistence.expensive_runs == 1

    release.set()
    leader_thread.join(timeout=5)
    assert not error
    assert handle_a is not None
    assert handle_a.state == "complete"
    assert handle_b.state == "complete"
    assert persistence.expensive_runs == 1
    assert persistence.persist_calls == 1
    assert orch_b.metrics.satisfaction_short_circuits == 1


def test_waiter_short_circuit_does_not_beat_leader_fanout_into_stream_terminal(
    sample_turn,
) -> None:
    """Lease wake must run after process terminal fan-out (#222 stream race).

    Without wake-after-fanout ordering, the waiter's satisfaction short-circuit
    completes with ``result_wire={}`` and its process fan-out reaches a
    scores-like stream listener *before* the leader's real ``rowComplete``, so
    the first-wins terminal becomes ``RowFailed``.
    """
    persistence = _SatisfiedAfterPersistPolicy()
    started = threading.Event()
    release = threading.Event()
    leader_row_complete = {"summary": "leader-exact"}

    def run_step(_job: dict[str, Any]) -> StepResult:
        persistence.expensive_runs += 1
        started.set()
        assert release.wait(timeout=5)
        return StepResult(
            outcome="persist",
            payload={"ok": True, "rowComplete": leader_row_complete},
        )

    registration = TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(SHARED_ID),
        compute=lambda _ctx: {"analyticId": SHARED_ID},
        export_catalog=empty_export_catalog_for(SHARED_ID),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
        ),
        persistence_policy=persistence,
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(("materialize", run_step),),
    )
    registry = build_compute_registry((registration,))
    ctx_a = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    ctx_b = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    orch_a = ComputeOrchestrator(ctx_a, compute_registry=registry)
    orch_b = ComputeOrchestrator(ctx_b, compute_registry=registry)
    scope = _shared_scope(sample_turn)

    # Mimic scores stream: first process-terminal wins; empty complete → failed.
    stream_terminals: list[str] = []
    claimed = False

    def stream_like_listener(_scope: ComputeScope, node: ComputeNodeRun) -> None:
        nonlocal claimed
        if claimed:
            return
        wire = node.result_wire
        if isinstance(wire, dict) and wire.get("rowComplete") is not None:
            stream_terminals.append("row_complete")
            claimed = True
            return
        if node.state == "complete":
            stream_terminals.append("row_failed_empty")
            claimed = True

    unregister = register_process_scope_terminal_listener(
        stream_like_listener,
        analytic_id=SHARED_ID,
    )
    try:
        handle_a = None
        error: list[BaseException] = []

        def run_leader() -> None:
            nonlocal handle_a
            try:
                handle_a = orch_a.submit(
                    ComputeRequest(scope=scope, priority_band="background"),
                )
            except BaseException as exc:  # noqa: BLE001
                error.append(exc)

        leader_thread = threading.Thread(target=run_leader)
        leader_thread.start()
        assert started.wait(timeout=5)

        handle_b = orch_b.submit(
            ComputeRequest(scope=scope, priority_band="stream_attached"),
        )
        assert orch_b.nodes[scope].state == "parked"

        release.set()
        leader_thread.join(timeout=5)
        assert not error
        assert handle_a is not None
        assert handle_a.state == "complete"
        assert handle_b.state == "complete"
        assert orch_b.metrics.satisfaction_short_circuits == 1
        assert stream_terminals == ["row_complete"], (
            "leader rowComplete must win the stream terminal; empty waiter "
            f"short-circuit must not claim first (got {stream_terminals!r})"
        )
    finally:
        unregister()


def test_leader_failure_releases_claim_so_waiter_becomes_leader(sample_turn) -> None:
    runs: list[str] = []

    def run_step(job: dict[str, Any]) -> StepResult:
        owner = job["owner"]
        runs.append(owner)
        if owner == "leader":
            raise RuntimeError("leader boom")
        return StepResult(outcome="persist", payload={"ok": True})

    registration = TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(SHARED_ID),
        compute=lambda _ctx: {"analyticId": SHARED_ID},
        export_catalog=empty_export_catalog_for(SHARED_ID),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(
            (
                "materialize",
                lambda scope, **_kwargs: {"scope": scope.analytic_id, "owner": "unset"},
            ),
        ),
        run_steps=(("materialize", run_step),),
    )
    registry = build_compute_registry((registration,))
    compute = registry[SHARED_ID]
    assert isinstance(compute.build_step_job_wire, dict)

    ctx_a = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    ctx_b = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    orch_a = ComputeOrchestrator(ctx_a, compute_registry=registry)
    orch_b = ComputeOrchestrator(ctx_b, compute_registry=registry)
    scope = _shared_scope(sample_turn)

    compute.build_step_job_wire["materialize"] = _build_wire_with_owner("leader")
    handle_a = orch_a.submit(ComputeRequest(scope=scope, priority_band="background"))
    assert handle_a.state == "failed"

    compute.build_step_job_wire["materialize"] = _build_wire_with_owner("waiter")
    handle_b = orch_b.submit(ComputeRequest(scope=scope, priority_band="stream_attached"))
    assert handle_b.state == "complete"
    assert runs == ["leader", "waiter"]


def test_process_scope_terminal_fanout_notifies_across_bindings(sample_turn) -> None:
    seen: list[ComputeScope] = []

    def listener(scope: ComputeScope, _node) -> None:
        seen.append(scope)

    unregister = register_process_scope_terminal_listener(listener, analytic_id="scores")
    scope = ComputeScope(
        analytic_id="scores",
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
        turn=sample_turn.settings.turn,
        player_id=first_player_id(sample_turn),
    )
    node = ComputeNodeRun(scope=scope, dependency_scopes=(), state="complete")
    notify_process_scope_terminal(scope, node)
    assert seen == [scope]

    other = ComputeScope(
        analytic_id="fleet",
        game_id=sample_turn.game.id,
        perspective=sample_turn.player.id,
        turn=sample_turn.settings.turn,
        player_id=first_player_id(sample_turn),
    )
    notify_process_scope_terminal(other, ComputeNodeRun(scope=other, dependency_scopes=()))
    assert seen == [scope]
    unregister()


def test_force_fresh_after_invalidate_reruns_when_unsatisfied(sample_turn) -> None:
    persistence = _SatisfiedAfterPersistPolicy()

    def run_step(_job: dict[str, Any]) -> StepResult:
        persistence.expensive_runs += 1
        return StepResult(outcome="persist", payload={"n": persistence.expensive_runs})

    registration = TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(SHARED_ID),
        compute=lambda _ctx: {"analyticId": SHARED_ID},
        export_catalog=empty_export_catalog_for(SHARED_ID),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(ComputeStepSpec(step_kind="materialize", backend="inline"),),
        ),
        persistence_policy=persistence,
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(("materialize", run_step),),
    )
    registry = build_compute_registry((registration,))
    ctx = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    orch = ComputeOrchestrator(ctx, compute_registry=registry)
    scope = _shared_scope(sample_turn)

    first = orch.submit(ComputeRequest(scope=scope))
    assert first.state == "complete"
    assert persistence.expensive_runs == 1

    persistence.satisfied = False
    second = orch.submit(ComputeRequest(scope=scope, force_fresh=True))
    assert second.state == "complete"
    assert persistence.expensive_runs == 2

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


def test_scope_lease_try_acquire_parks_same_or_lower_priority() -> None:
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
            priority_band="stream_attached",
            on_wake=lambda: wakes.append("a"),
        )
        == "acquired"
    )
    assert (
        lease.try_acquire(
            key,
            orchestrator_id=2,
            priority_band="background",
            on_wake=lambda: wakes.append("b"),
        )
        == "parked"
    )
    callbacks = lease.release(key, orchestrator_id=1)
    assert len(callbacks) == 1
    callbacks[0]()
    assert wakes == ["b"]


def test_scope_lease_higher_priority_adopts_unsealed_claim() -> None:
    lease = get_process_scope_lease()
    scope = ComputeScope(
        analytic_id="a",
        game_id=1,
        perspective=1,
        turn=1,
        player_id=1,
    )
    key = ScopeStepClaimKey(scope=scope, step_kind="materialize")
    assert (
        lease.try_acquire(
            key,
            orchestrator_id=1,
            priority_band="background",
            on_wake=lambda: None,
        )
        == "acquired"
    )
    assert (
        lease.try_acquire(
            key,
            orchestrator_id=2,
            priority_band="stream_attached",
            on_wake=lambda: None,
        )
        == "adopted"
    )
    assert lease.holder(key) == (2, "stream_attached")
    assert not lease.is_execution_started(key)
    assert lease.seal_for_execution(key, orchestrator_id=1).outcome == "lost"
    assert lease.seal_for_execution(key, orchestrator_id=2).outcome == "sealed"
    assert lease.is_execution_started(key)


def test_scope_lease_adopt_blocked_after_seal() -> None:
    lease = get_process_scope_lease()
    scope = ComputeScope(
        analytic_id="a",
        game_id=1,
        perspective=1,
        turn=1,
        player_id=1,
    )
    key = ScopeStepClaimKey(scope=scope, step_kind="materialize")
    assert (
        lease.try_acquire(
            key,
            orchestrator_id=1,
            priority_band="background",
            on_wake=lambda: None,
        )
        == "acquired"
    )
    assert lease.seal_for_execution(key, orchestrator_id=1).outcome == "sealed"
    assert (
        lease.try_acquire(
            key,
            orchestrator_id=2,
            priority_band="stream_attached",
            on_wake=lambda: None,
        )
        == "parked"
    )
    assert lease.holder(key) == (1, "background")


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


def test_seal_retry_second_loss_registers_waiter_and_wakes(sample_turn) -> None:
    """Second seal lost must park via try_acquire so leader release wakes (#222).

    Race: first seal lost → claim freed → re-acquire → adopted again before retry
    seal. Parking on that second lost without registering a waiter deadlocks.
    """
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
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(
            (
                "materialize",
                lambda _job: StepResult(outcome="persist", payload={"ok": True}),
            ),
        ),
    )
    registry = build_compute_registry((registration,))
    ctx = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
    orch = ComputeOrchestrator(ctx, compute_registry=registry)
    scope = _shared_scope(sample_turn)
    step = ComputeStepSpec(step_kind="materialize", backend="inline")
    node = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state="running",
        priority_band="background",
    )
    node.held_lease_step_kinds.add("materialize")
    orch._nodes[scope] = node

    lease = get_process_scope_lease()
    key = ScopeStepClaimKey(scope=scope, step_kind="materialize")
    peer_id = id(orch) + 1
    assert (
        lease.try_acquire(
            key,
            orchestrator_id=id(orch),
            priority_band="background",
            on_wake=lambda: None,
        )
        == "acquired"
    )
    assert (
        lease.try_acquire(
            key,
            orchestrator_id=peer_id,
            priority_band="stream_attached",
            on_wake=lambda: None,
        )
        == "adopted"
    )

    real_seal = lease.seal_for_execution
    real_acquire = lease.try_acquire
    seal_losses = 0
    steal_after_victim_reacquire = True

    def seal_freeing_peer_after_first_loss(claim_key, *, orchestrator_id):
        nonlocal seal_losses
        result = real_seal(claim_key, orchestrator_id=orchestrator_id)
        if result.outcome == "lost":
            seal_losses += 1
            if seal_losses == 1:
                # Free the claim so recovery re-acquires, enabling a second adopt.
                lease.release(claim_key, orchestrator_id=peer_id)
        return result

    def acquire_then_steal_once(
        claim_key,
        *,
        orchestrator_id,
        priority_band,
        on_wake,
    ):
        nonlocal steal_after_victim_reacquire
        outcome = real_acquire(
            claim_key,
            orchestrator_id=orchestrator_id,
            priority_band=priority_band,
            on_wake=on_wake,
        )
        if (
            steal_after_victim_reacquire
            and orchestrator_id == id(orch)
            and outcome in {"acquired", "adopted"}
        ):
            steal_after_victim_reacquire = False
            assert (
                real_acquire(
                    claim_key,
                    orchestrator_id=peer_id,
                    priority_band="stream_attached",
                    on_wake=lambda: None,
                )
                == "adopted"
            )
        return outcome

    lease.seal_for_execution = seal_freeing_peer_after_first_loss  # type: ignore[method-assign]
    lease.try_acquire = acquire_then_steal_once  # type: ignore[method-assign]
    try:
        assert orch._seal_scope_lease_or_park(node, step) is False
    finally:
        lease.seal_for_execution = real_seal  # type: ignore[method-assign]
        lease.try_acquire = real_acquire  # type: ignore[method-assign]

    assert seal_losses >= 2
    assert node.state == "parked"
    assert "materialize" not in node.held_lease_step_kinds
    assert orch.metrics.lease_parks == 1
    assert lease.holder(key) == (peer_id, "stream_attached")

    wake_callbacks = lease.release(key, orchestrator_id=peer_id)
    assert len(wake_callbacks) == 1
    wake_callbacks[0]()
    # Wake re-queues and dispatches; unsatisfied stub policy runs the step to complete.
    assert node.state == "complete"


def test_stream_attached_adopts_unsealed_background_claim(sample_turn) -> None:
    """Higher-priority stream adopts before background seals expensive work."""
    persistence = _SatisfiedAfterPersistPolicy()
    wire_started = threading.Event()
    allow_wire = threading.Event()
    run_owners: list[str] = []

    def build_wire(scope, **_kwargs):
        wire_started.set()
        assert allow_wire.wait(timeout=5)
        return {"scope": scope.analytic_id, "owner": "background-wire"}

    def run_step(job: dict[str, Any]) -> StepResult:
        run_owners.append(job.get("owner", "unknown"))
        persistence.expensive_runs += 1
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
        build_step_job_wires=(("materialize", build_wire),),
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

    handle_a = None
    error: list[BaseException] = []

    def run_background() -> None:
        nonlocal handle_a
        try:
            handle_a = orch_a.submit(
                ComputeRequest(scope=scope, priority_band="background"),
            )
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    background_thread = threading.Thread(target=run_background)
    background_thread.start()
    assert wire_started.wait(timeout=5)

    compute.build_step_job_wire["materialize"] = _build_wire_with_owner("stream")
    handle_b = orch_b.submit(
        ComputeRequest(scope=scope, priority_band="stream_attached"),
    )
    assert orch_b.metrics.lease_adopts == 1

    allow_wire.set()
    background_thread.join(timeout=5)
    assert not error
    assert handle_a is not None
    assert handle_a.state == "complete"
    assert handle_b.state == "complete"
    assert run_owners == ["stream"]
    assert persistence.expensive_runs == 1
    assert orch_a.metrics.satisfaction_short_circuits == 1
    assert orch_a.metrics.inline_executions == 0


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


def test_profile_continue_retains_materialize_claim_during_later_step(sample_turn) -> None:
    """Leader materialize→tier_solve must not free materialize for peer rematerialize.

    Releasing the materialize claim on profile continue would let a peer binding
    rematerialize while the leader is still non-terminal on tier_solve, defeating
    cross-binding dedupe for the inline leg the lease protects (#222 / review 06).
    """
    persistence = _SatisfiedAfterPersistPolicy()
    materialize_runs = 0
    tier_started = threading.Event()
    tier_release = threading.Event()

    def run_materialize(_job: dict[str, Any]) -> StepResult:
        nonlocal materialize_runs
        materialize_runs += 1
        return StepResult(outcome="continue", payload={"materialized": True})

    def run_tier_solve(_job: dict[str, Any]) -> StepResult:
        tier_started.set()
        assert tier_release.wait(timeout=5)
        return StepResult(outcome="persist", payload={"ok": True})

    registration = TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(SHARED_ID),
        compute=lambda _ctx: {"analyticId": SHARED_ID},
        export_catalog=empty_export_catalog_for(SHARED_ID),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(
                ComputeStepSpec(step_kind="materialize", backend="inline"),
                ComputeStepSpec(step_kind="tier_solve", backend="inline"),
            ),
        ),
        persistence_policy=persistence,
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
            ("tier_solve", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(
            ("materialize", run_materialize),
            ("tier_solve", run_tier_solve),
        ),
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
    assert tier_started.wait(timeout=5)
    assert materialize_runs == 1
    assert "materialize" in orch_a.nodes[scope].held_lease_step_kinds
    assert "tier_solve" in orch_a.nodes[scope].held_lease_step_kinds

    handle_b = orch_b.submit(
        ComputeRequest(scope=scope, priority_band="stream_attached"),
    )
    assert orch_b.nodes[scope].state == "parked"
    assert orch_b.metrics.lease_parks == 1
    assert materialize_runs == 1

    tier_release.set()
    leader_thread.join(timeout=5)
    assert not error
    assert handle_a is not None
    assert handle_a.state == "complete"
    assert handle_b.state == "complete"
    assert materialize_runs == 1
    assert persistence.persist_calls == 1
    assert orch_b.metrics.satisfaction_short_circuits == 1


def test_distinct_entry_step_kinds_do_not_suppress_each_other(sample_turn) -> None:
    """Independent entry at tier_solve must not park behind a materialize-only claim.

    Claim keys remain scope+step_kind: a peer that enters at tier_solve while the
    leader still holds only materialize (before continue) may acquire tier_solve.
    """
    materialize_started = threading.Event()
    materialize_release = threading.Event()
    tier_runs = 0

    def run_materialize(_job: dict[str, Any]) -> StepResult:
        materialize_started.set()
        assert materialize_release.wait(timeout=5)
        return StepResult(outcome="persist", payload={"m": True})

    def run_tier_solve(_job: dict[str, Any]) -> StepResult:
        nonlocal tier_runs
        tier_runs += 1
        return StepResult(outcome="complete", payload={"t": True})

    registration = TurnAnalyticRegistration(
        catalog_entry=_catalog_entry(SHARED_ID),
        compute=lambda _ctx: {"analyticId": SHARED_ID},
        export_catalog=empty_export_catalog_for(SHARED_ID),
        scope_key_spec=_ROW_SCOPE_KEY,
        compute_profile=AnalyticComputeProfile(
            steps=(
                ComputeStepSpec(step_kind="materialize", backend="inline"),
                ComputeStepSpec(step_kind="tier_solve", backend="inline"),
            ),
        ),
        persistence_policy=_StubPersistencePolicy(),
        build_step_job_wires=(
            ("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
            ("tier_solve", lambda scope, **_kwargs: {"scope": scope.analytic_id}),
        ),
        run_steps=(
            ("materialize", run_materialize),
            ("tier_solve", run_tier_solve),
        ),
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
    assert materialize_started.wait(timeout=5)

    handle_b = orch_b.submit(
        ComputeRequest(scope=scope, step_kind="tier_solve", priority_band="stream_attached"),
    )
    assert handle_b.state == "complete"
    assert tier_runs == 1
    assert orch_b.metrics.lease_parks == 0

    materialize_release.set()
    leader_thread.join(timeout=5)
    assert not error
    assert handle_a is not None
    assert handle_a.state == "complete"


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

"""Regression tests for cancelled tier jobs and stale persistence."""

from __future__ import annotations

import threading
import time

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_row_runner import (
    TierJobOutcome,
    run_inference_tier_job,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.solver import STATUS_NO_EXACT_SOLUTION
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.analytics.scores.tier_row_run_registry import get_row_run
from api.compute.pools import reset_compute_worker_pool_for_tests
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend


def _session_for_player(
    sample_turn,
    *,
    player_id: int,
    game_id: int = 628580,
    perspective: int = 1,
) -> InferenceRowStreamSession:
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    return InferenceRowStreamSession(
        player_id=player_id,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=game_id,
        perspective=perspective,
        turn_number=sample_turn.settings.turn,
    )


def _wait_until(predicate, *, timeout_seconds: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met before timeout")


def _patch_scores_dag_without_fleet_deps(monkeypatch) -> None:
    from api.compute.dag import PlannedComputeNode
    from api.compute.dag import plan_compute_dag as real_plan
    from api.compute.scope import normalize_export_scope_to_compute_scope

    def scores_only_dag(ctx, analytic_id, export_scope, *, compute_registry, force_root=False):
        if analytic_id != "scores":
            return real_plan(
                ctx,
                analytic_id,
                export_scope,
                compute_registry=compute_registry,
                force_root=force_root,
            )
        registration = compute_registry[analytic_id]
        scope = normalize_export_scope_to_compute_scope(
            export_scope,
            analytic_id=analytic_id,
            scope_key_spec=registration.scope_key_spec,
        )
        return (
            PlannedComputeNode(
                scope=scope,
                export_scope=export_scope,
                dependency_scopes=(),
            ),
        )

    monkeypatch.setattr("api.compute.orchestrator.plan_compute_dag", scores_only_dag)


def test_cancelled_tier_job_does_not_persist_after_run_removed(sample_turn, monkeypatch):
    """A zombie worker must not persist or resurrect a row run cancelled mid-tier."""
    reset_compute_worker_pool_for_tests(worker_count=1)
    reset_inference_row_scheduler_for_tests()
    _patch_scores_dag_without_fleet_deps(monkeypatch)
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    scheduler = InferenceRowScheduler()
    try:
        scope = InferenceStreamScope(
            game_id=628580,
            perspective=1,
            turn_number=sample_turn.settings.turn,
        )
        scheduler.begin_scope(scope)

        tier_step_started = threading.Event()
        tier_step_gate = threading.Event()

        outcome_computed = threading.Event()
        release_outcome = threading.Event()

        short_ladder = resolve_tier_policies(None)[:1]

        def fake_tier_step(
            state: PolicyLadderState,
            observation,
            turn,
            *,
            time_limit_seconds=None,
            cancel_token=None,
            on_admitted=None,
        ) -> None:
            tier_step_started.set()
            tier_step_gate.wait(timeout=2.0)
            state.policy_steps_attempted.append(state.policy_steps[state.next_step_index].id)
            state.next_step_index += 1
            state.ladder_complete = True

        real_run_inference_tier_job = run_inference_tier_job

        def gated_run_inference_tier_job(run, callbacks):
            real_run_inference_tier_job(run, callbacks)
            outcome = TierJobOutcome(
                row_complete=row_complete_with_summary(
                    InferenceResult(
                        status=STATUS_NO_EXACT_SOLUTION,
                        solutions=(),
                        diagnostics={},
                    ),
                    summary="zombie tier result",
                ),
            )
            outcome_computed.set()
            release_outcome.wait(timeout=2.0)
            return outcome

        monkeypatch.setattr(
            "api.analytics.military_score_inference.inference_row_runner.run_policy_ladder_tier_step",
            fake_tier_step,
        )
        monkeypatch.setattr(
            "api.analytics.scores.compute_orchestration.run_inference_tier_job",
            gated_run_inference_tier_job,
        )

        player_id = sample_turn.scores[0].ownerid
        session = _session_for_player(sample_turn, player_id=player_id)
        turn_number = sample_turn.settings.turn

        scheduler.enqueue_tier_ladder(session)
        row_run = get_row_run(session.run_id)
        assert row_run is not None
        row_run.ladder_state = PolicyLadderState(policy_steps=short_ladder)

        _wait_until(tier_step_started.is_set)
        scheduler.cancel_row_run(run_id := session.run_id)
        persistence.delete_row(628580, 1, turn_number, player_id)
        tier_step_gate.set()

        _wait_until(outcome_computed.is_set)

        release_outcome.set()
        time.sleep(0.1)

        assert persistence.get_row(628580, 1, turn_number, player_id) is None
        assert run_id not in scheduler._runs
    finally:
        reset_inference_row_scheduler_for_tests()


def test_begin_scope_turn_change_aborts_in_flight_orchestrator_nodes(
    sample_turn,
    monkeypatch,
):
    """Scope-change preempt must abort DAG nodes, not only unregister RowRuns.

    Fingerprint: background scores@t3 still ``running`` after stream begin_scope(t8)
    cleared the RowRun; persist then raised ``missing RowRun`` and failed the player.
    """
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.errors import ComputeScopeAbortedError
    from api.compute.runtime import get_compute_orchestrator, reset_compute_orchestrator_for_tests
    from api.compute.scope import ComputeScope

    reset_compute_worker_pool_for_tests(worker_count=1)
    reset_inference_row_scheduler_for_tests()
    reset_compute_orchestrator_for_tests()
    _patch_scores_dag_without_fleet_deps(monkeypatch)
    scheduler = InferenceRowScheduler()
    try:
        turn_number = sample_turn.settings.turn
        scope_a = InferenceStreamScope(
            game_id=628580,
            perspective=1,
            turn_number=turn_number,
        )
        scope_b = InferenceStreamScope(
            game_id=628580,
            perspective=1,
            turn_number=turn_number + 1,
        )
        scheduler.begin_scope(scope_a)

        tier_step_started = threading.Event()
        tier_step_gate = threading.Event()

        def fake_tier_step(
            state: PolicyLadderState,
            observation,
            turn,
            *,
            time_limit_seconds=None,
            cancel_token=None,
            on_admitted=None,
        ) -> None:
            tier_step_started.set()
            tier_step_gate.wait(timeout=2.0)
            state.policy_steps_attempted.append(state.policy_steps[state.next_step_index].id)
            state.next_step_index += 1
            state.ladder_complete = True

        monkeypatch.setattr(
            "api.analytics.military_score_inference.inference_row_runner.run_policy_ladder_tier_step",
            fake_tier_step,
        )

        player_id = sample_turn.scores[0].ownerid
        session = _session_for_player(sample_turn, player_id=player_id)
        short_ladder = resolve_tier_policies(None)[:1]
        scheduler.enqueue_tier_ladder(session)
        row_run = get_row_run(session.run_id)
        assert row_run is not None
        row_run.ladder_state = PolicyLadderState(policy_steps=short_ladder)

        root_scope = ComputeScope(
            analytic_id=SCORES_ANALYTIC_ID,
            game_id=628580,
            perspective=1,
            turn=turn_number,
            player_id=player_id,
        )
        _wait_until(tier_step_started.is_set)

        scheduler.begin_scope(scope_b)

        assert session.cancel_token.is_cancelled()
        assert get_row_run(session.run_id) is None
        node = get_compute_orchestrator().nodes.get(root_scope)
        assert node is not None
        assert node.state == "failed"
        assert isinstance(node.error, ComputeScopeAbortedError)

        tier_step_gate.set()
        time.sleep(0.1)
        # Worker finish must be ignored; node stays abort-failed (not missing-RowRun).
        assert node.state == "failed"
        assert isinstance(node.error, ComputeScopeAbortedError)
        assert "missing RowRun" not in str(node.error)
    finally:
        tier_step_gate.set()
        reset_inference_row_scheduler_for_tests()
        reset_compute_orchestrator_for_tests()


def test_cancel_between_tier_finish_and_emit_does_not_persist(sample_turn, monkeypatch):
    """Cancel after tier work returns but before row-complete emit must not write storage."""
    reset_compute_worker_pool_for_tests(worker_count=1)
    reset_inference_row_scheduler_for_tests()
    _patch_scores_dag_without_fleet_deps(monkeypatch)
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    scheduler = InferenceRowScheduler()
    try:
        scope = InferenceStreamScope(
            game_id=628580,
            perspective=1,
            turn_number=sample_turn.settings.turn,
        )
        scheduler.begin_scope(scope)

        finalize_entered = threading.Event()
        finalize_gate = threading.Event()
        original_finalize = InferenceRowScheduler._finalize_row_run

        def gated_finalize(self, session):
            finalize_entered.set()
            finalize_gate.wait(timeout=2.0)
            original_finalize(self, session)

        monkeypatch.setattr(InferenceRowScheduler, "_finalize_row_run", gated_finalize)

        short_ladder = resolve_tier_policies(None)[:1]

        def fast_tier_step(
            state: PolicyLadderState,
            observation,
            turn,
            *,
            time_limit_seconds=None,
            cancel_token=None,
            on_admitted=None,
        ) -> None:
            state.policy_steps_attempted.append(state.policy_steps[state.next_step_index].id)
            state.next_step_index += 1
            state.ladder_complete = True

        monkeypatch.setattr(
            "api.analytics.military_score_inference.inference_row_runner.run_policy_ladder_tier_step",
            fast_tier_step,
        )

        player_id = sample_turn.scores[0].ownerid
        session = _session_for_player(sample_turn, player_id=player_id)
        turn_number = sample_turn.settings.turn

        scheduler.enqueue_tier_ladder(session)
        row_run = get_row_run(session.run_id)
        assert row_run is not None
        row_run.ladder_state = PolicyLadderState(policy_steps=short_ladder)

        _wait_until(finalize_entered.is_set)
        scheduler.cancel_row_run(run_id := session.run_id)
        persistence.delete_row(628580, 1, turn_number, player_id)
        finalize_gate.set()

        _wait_until(lambda: run_id not in scheduler._runs, timeout_seconds=3.0)
        time.sleep(0.05)

        assert persistence.get_row(628580, 1, turn_number, player_id) is None
        assert run_id not in scheduler._runs
    finally:
        reset_inference_row_scheduler_for_tests()

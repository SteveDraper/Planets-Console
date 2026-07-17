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
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_NO_EXACT_SOLUTION,
)
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

    monkeypatch.setattr("api.compute.orchestrator_submission.plan_compute_dag", scores_only_dag)


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


def test_begin_scope_other_turn_leaves_background_row_runs_running(sample_turn):
    """Opening a later turn's stream must not tear down earlier-turn background warm.

    Fingerprint: begin_scope(t8) while scores@t3 background was in flight aborted all
    t3 nodes; fleet stayed waiting_deps forever (no fleet rows).
    """
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.scores.tier_row_run_registry import (
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope

    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    scheduler = InferenceRowScheduler()
    try:
        turn_number = sample_turn.settings.turn
        player_id = sample_turn.scores[0].ownerid
        session = _session_for_player(sample_turn, player_id=player_id)
        row_run = RowRun(session)
        register_row_run(row_run)
        with scheduler._lock:
            scheduler._runs[session.run_id] = ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=628580,
                perspective=1,
                turn=turn_number,
                player_id=player_id,
            )

        # First stream claim for a *later* turn (no prior active scope).
        scheduler.begin_scope(
            InferenceStreamScope(
                game_id=628580,
                perspective=1,
                turn_number=turn_number + 1,
            )
        )

        assert get_row_run(session.run_id) is not None
        assert session.run_id in scheduler._runs
        assert not session.cancel_token.is_cancelled()
    finally:
        reset_inference_row_scheduler_for_tests()
        reset_tier_row_run_registry_for_tests()


def test_begin_scope_prior_turn_preempts_only_that_turn(sample_turn):
    """Switching stream turns preempts the prior turn's runs, not other turns."""
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.scores.tier_row_run_registry import (
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope

    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    scheduler = InferenceRowScheduler()
    try:
        turn_number = sample_turn.settings.turn
        player_id = sample_turn.scores[0].ownerid

        def _register_for_turn(turn: int) -> InferenceRowStreamSession:
            session = _session_for_player(sample_turn, player_id=player_id)
            # Override turn_number on a fresh session for the synthetic prior turn.
            session = InferenceRowStreamSession(
                player_id=player_id,
                observation=session.observation,
                turn=sample_turn,
                game_id=628580,
                perspective=1,
                turn_number=turn,
            )
            register_row_run(RowRun(session))
            with scheduler._lock:
                scheduler._runs[session.run_id] = ComputeScope(
                    analytic_id=SCORES_ANALYTIC_ID,
                    game_id=628580,
                    perspective=1,
                    turn=turn,
                    player_id=player_id,
                )
            return session

        prior_session = _register_for_turn(turn_number)
        other_session = _register_for_turn(turn_number + 5)

        scheduler.begin_scope(
            InferenceStreamScope(
                game_id=628580,
                perspective=1,
                turn_number=turn_number,
            )
        )
        # Switch away from prior turn -- only that turn is detached (not cancelled).
        scheduler.begin_scope(
            InferenceStreamScope(
                game_id=628580,
                perspective=1,
                turn_number=turn_number + 1,
            )
        )

        assert not prior_session.cancel_token.is_cancelled()
        assert prior_session.run_id not in scheduler._runs
        assert get_row_run(prior_session.run_id) is None

        assert not other_session.cancel_token.is_cancelled()
        assert other_session.run_id in scheduler._runs
        assert get_row_run(other_session.run_id) is not None
    finally:
        reset_inference_row_scheduler_for_tests()
        reset_tier_row_run_registry_for_tests()


def test_begin_scope_detach_allows_durable_persist_while_run_still_visible(
    sample_turn,
):
    """Detach must not cancel; a still-registered RowRun must still persist.

    Fingerprint: cancel-on-detach raced with ScoresPersistencePolicy, which skips
    cancelled runs -- durable evidence dropped even though the worker finished a
    RowComplete. Detach must leave no cancellation fence.
    """
    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.options import TurnAnalyticsOptions
    from api.analytics.scores.compute_orchestration import ScoresPersistencePolicy
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores.tier_row_run_registry import (
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope
    from api.storage.memory_asset import MemoryAssetBackend

    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    scheduler = InferenceRowScheduler()
    try:
        turn_number = sample_turn.settings.turn
        player_id = sample_turn.scores[0].ownerid
        scope = InferenceStreamScope(
            game_id=628580,
            perspective=1,
            turn_number=turn_number,
        )
        first_token = scheduler.begin_scope(scope)
        session = _session_for_player(sample_turn, player_id=player_id)
        row_run = RowRun(session)
        register_row_run(row_run)
        with scheduler._lock:
            scheduler._runs[session.run_id] = ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=628580,
                perspective=1,
                turn=turn_number,
                player_id=player_id,
            )

        # Same-scope preempt detaches stream ownership without cancelling solve.
        second_token = scheduler.begin_scope(scope)
        assert second_token != first_token
        assert not scheduler.owns_table_stream(first_token)
        assert not session.cancel_token.is_cancelled()
        assert session.run_id not in scheduler._runs
        assert get_row_run(session.run_id) is None

        # Race window: RowRun still visible to persist, token not cancelled.
        register_row_run(row_run)
        assert get_row_run(session.run_id) is row_run
        assert not session.cancel_token.is_cancelled()

        ctx = make_analytic_query_context(
            sample_turn,
            TurnAnalyticsOptions(),
            export_services={
                SCORES_ANALYTIC_ID: ScoresExportContext(persistence=persistence),
            },
        )
        row_complete = row_complete_with_summary(
            InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
            summary="detach must not block persist",
        )
        ScoresPersistencePolicy().persist(
            ctx,
            ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=628580,
                perspective=1,
                turn=turn_number,
                player_id=player_id,
            ),
            {"runId": session.run_id, "rowComplete": row_complete},
        )

        stored = persistence.get_row(628580, 1, turn_number, player_id)
        assert stored is not None
        assert stored.summary == "detach must not block persist"

        # Explicit cancel still blocks persist while the run is registered.
        persistence.delete_row(628580, 1, turn_number, player_id)
        session.cancel_token.cancel()
        ScoresPersistencePolicy().persist(
            ctx,
            ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=628580,
                perspective=1,
                turn=turn_number,
                player_id=player_id,
            ),
            {"runId": session.run_id, "rowComplete": row_complete},
        )
        assert persistence.get_row(628580, 1, turn_number, player_id) is None
    finally:
        reset_inference_row_scheduler_for_tests()
        reset_tier_row_run_registry_for_tests()


def test_cancel_after_unregister_blocks_persist_via_fence(sample_turn):
    """cancel_run fence must survive RowRun removal so late persist skips.

    Fingerprint: cancel cancelled the token and unregistered before abort; persist
    saw ``get_row_run is None`` and wrote durable evidence for cancelled work.
    """
    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.options import TurnAnalyticsOptions
    from api.analytics.scores.compute_orchestration import ScoresPersistencePolicy
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores.tier_row_run_registry import (
        get_row_run,
        is_row_run_cancelled,
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope
    from api.storage.memory_asset import MemoryAssetBackend

    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    scheduler = InferenceRowScheduler()
    try:
        turn_number = sample_turn.settings.turn
        player_id = sample_turn.scores[0].ownerid
        scheduler.begin_scope(
            InferenceStreamScope(
                game_id=628580,
                perspective=1,
                turn_number=turn_number,
            )
        )
        session = _session_for_player(sample_turn, player_id=player_id)
        row_run = RowRun(session)
        register_row_run(row_run)
        with scheduler._lock:
            scheduler._runs[session.run_id] = ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=628580,
                perspective=1,
                turn=turn_number,
                player_id=player_id,
            )

        scheduler.cancel_run(session.run_id)
        assert get_row_run(session.run_id) is None
        assert is_row_run_cancelled(session.run_id)
        assert session.cancel_token.is_cancelled()

        ctx = make_analytic_query_context(
            sample_turn,
            TurnAnalyticsOptions(),
            export_services={
                SCORES_ANALYTIC_ID: ScoresExportContext(persistence=persistence),
            },
        )
        row_complete = row_complete_with_summary(
            InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
            summary="cancel-after-unregister must not persist",
        )
        ScoresPersistencePolicy().persist(
            ctx,
            ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=628580,
                perspective=1,
                turn=turn_number,
                player_id=player_id,
            ),
            {"runId": session.run_id, "rowComplete": row_complete},
        )
        assert persistence.get_row(628580, 1, turn_number, player_id) is None
    finally:
        reset_inference_row_scheduler_for_tests()
        reset_tier_row_run_registry_for_tests()


def test_cancel_fence_blocks_late_persist_under_high_churn(sample_turn):
    """An explicit cancel fence must not expire before late persist is rejected."""
    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.options import TurnAnalyticsOptions
    from api.analytics.scores import tier_row_run_registry as reg
    from api.analytics.scores.compute_orchestration import ScoresPersistencePolicy
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope
    from api.storage.memory_asset import MemoryAssetBackend

    reset_inference_row_scheduler_for_tests()
    reg.reset_tier_row_run_registry_for_tests()
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    scheduler = InferenceRowScheduler()
    try:
        turn_number = sample_turn.settings.turn
        player_id = sample_turn.scores[0].ownerid
        scheduler.begin_scope(
            InferenceStreamScope(
                game_id=628580,
                perspective=1,
                turn_number=turn_number,
            )
        )
        for index in range(5_000):
            reg.mark_row_run_cancelled(f"unrelated-run-{index}")

        session = _session_for_player(sample_turn, player_id=player_id)
        row_run = RowRun(session)
        reg.register_row_run(row_run)
        with scheduler._lock:
            scheduler._runs[session.run_id] = ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=628580,
                perspective=1,
                turn=turn_number,
                player_id=player_id,
            )

        scheduler.cancel_run(session.run_id)
        assert reg.is_row_run_cancelled(session.run_id)
        assert reg.is_row_run_cancelled("unrelated-run-0")

        ctx = make_analytic_query_context(
            sample_turn,
            TurnAnalyticsOptions(),
            export_services={
                SCORES_ANALYTIC_ID: ScoresExportContext(persistence=persistence),
            },
        )
        row_complete = row_complete_with_summary(
            InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
            summary="cancelled high-churn run must not persist",
        )
        ScoresPersistencePolicy().persist(
            ctx,
            ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=628580,
                perspective=1,
                turn=turn_number,
                player_id=player_id,
            ),
            {"runId": session.run_id, "rowComplete": row_complete},
        )
        assert persistence.get_row(628580, 1, turn_number, player_id) is None
    finally:
        reset_inference_row_scheduler_for_tests()
        reg.reset_tier_row_run_registry_for_tests()


def test_stream_disconnect_detaches_without_fence_and_allows_persist(sample_turn):
    """Disconnect detaches without a cancellation fence; finish may persist."""
    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.options import TurnAnalyticsOptions
    from api.analytics.scores.compute_orchestration import ScoresPersistencePolicy
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores.tier_row_run_registry import (
        get_row_run,
        is_row_run_cancelled,
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope
    from api.storage.memory_asset import MemoryAssetBackend

    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    scheduler = InferenceRowScheduler()
    try:
        turn_number = sample_turn.settings.turn
        player_id = sample_turn.scores[0].ownerid
        scope = InferenceStreamScope(
            game_id=628580,
            perspective=1,
            turn_number=turn_number,
        )
        stream_token = scheduler.begin_scope(scope)
        session = _session_for_player(sample_turn, player_id=player_id)
        row_run = RowRun(session)
        register_row_run(row_run)
        with scheduler._lock:
            scheduler._runs[session.run_id] = ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=628580,
                perspective=1,
                turn=turn_number,
                player_id=player_id,
            )

        scheduler.detach_inference_stream(scope, (session,), stream_token=stream_token)
        assert get_row_run(session.run_id) is None
        assert not is_row_run_cancelled(session.run_id)
        assert not session.cancel_token.is_cancelled()

        ctx = make_analytic_query_context(
            sample_turn,
            TurnAnalyticsOptions(),
            export_services={
                SCORES_ANALYTIC_ID: ScoresExportContext(persistence=persistence),
            },
        )
        row_complete = row_complete_with_summary(
            InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
            summary="detach-missing-run may persist",
        )
        ScoresPersistencePolicy().persist(
            ctx,
            ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=628580,
                perspective=1,
                turn=turn_number,
                player_id=player_id,
            ),
            {"runId": session.run_id, "rowComplete": row_complete},
        )
        stored = persistence.get_row(628580, 1, turn_number, player_id)
        assert stored is not None
        assert stored.summary == "detach-missing-run may persist"
    finally:
        reset_inference_row_scheduler_for_tests()
        reset_tier_row_run_registry_for_tests()


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

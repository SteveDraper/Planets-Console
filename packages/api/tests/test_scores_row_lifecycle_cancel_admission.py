"""Cancel admission and seal regressions for scores row-run lifecycle."""

from __future__ import annotations

import threading
import time

from api.analytics.military_score_inference.inference_row_runner import (
    TierJobOutcome,
    run_inference_tier_job,
)
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
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

from tests.scores_row_lifecycle_test_helpers import (
    _patch_scores_dag_without_fleet_deps,
    _session_for_player,
    _wait_until,
)


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


def test_lifecycle_cancel_sets_token_cancel_deny_and_resolution(sample_turn):
    """cancel_run applies token + CANCEL_DENY admission + stream CANCELED as one intent.

    Detach must not set these. Compact CANCEL_DENY admission is the durable persist
    refuse; stream ``CANCELED`` only silences delivery.
    """
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.scores.tier_row_run_registry import (
        get_persist_admission,
        get_row_run_phase,
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope
    from api.streaming.table_stream.row_run_admission import PersistAdmission
    from api.streaming.table_stream.row_stream_resolution import (
        RowStreamResolutionState,
    )
    from api.streaming.table_stream.row_stream_resolution_registry import (
        get_stream_resolution,
    )

    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
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
        register_row_run(RowRun(session))
        with scheduler._lock:
            scheduler._runs[session.run_id] = ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=628580,
                perspective=1,
                turn=turn_number,
                player_id=player_id,
            )
            scheduler._execution_generation_by_run_id[session.run_id] = 7

        assert not session.cancel_token.is_cancelled()
        assert get_persist_admission(session.run_id) is PersistAdmission.ALLOW
        assert get_stream_resolution(session.run_id) is None

        scheduler.cancel_run(session.run_id)

        assert session.cancel_token.is_cancelled()
        assert get_row_run_phase(session.run_id) is None
        assert get_persist_admission(session.run_id) is PersistAdmission.CANCEL_DENY
        resolution = get_stream_resolution(session.run_id)
        assert resolution is not None
        assert resolution.state is RowStreamResolutionState.CANCELED
        assert session.run_id not in scheduler._runs
    finally:
        reset_inference_row_scheduler_for_tests()
        reset_tier_row_run_registry_for_tests()


def test_cancel_after_detach_blocks_persist_via_cancel_deny(sample_turn):
    """cancel_run CANCEL_DENY admission must survive scheduler removal so late persist skips.

    Fingerprint: cancel cancelled the token and dropped scheduler maps before abort;
    persist must still see compact CANCEL_DENY admission and refuse the write.
    """
    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.options import TurnAnalyticsOptions
    from api.analytics.scores.compute_orchestration import ScoresPersistencePolicy
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores.tier_row_run_registry import (
        get_persist_admission,
        get_row_run,
        get_row_run_phase,
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope
    from api.storage.memory_asset import MemoryAssetBackend
    from api.streaming.table_stream.row_run_admission import PersistAdmission

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
        assert get_row_run_phase(session.run_id) is None
        assert get_persist_admission(session.run_id) is PersistAdmission.CANCEL_DENY
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
            summary="cancel-after-retire must not persist",
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
        assert get_persist_admission(session.run_id) is PersistAdmission.ABSENT
    finally:
        reset_inference_row_scheduler_for_tests()
        reset_tier_row_run_registry_for_tests()


def test_cancel_deny_blocks_late_persist_under_churn(sample_turn):
    """CANCEL_DENY admission must still block late persist when other runs also churn."""
    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.options import TurnAnalyticsOptions
    from api.analytics.scores import tier_row_run_registry as reg
    from api.analytics.scores.compute_orchestration import ScoresPersistencePolicy
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope
    from api.storage.memory_asset import MemoryAssetBackend
    from api.streaming.table_stream.row_run_admission import PersistAdmission
    from api.streaming.table_stream.row_stream_resolution_registry import (
        reset_stream_resolution_registry_for_tests,
    )

    reset_inference_row_scheduler_for_tests()
    reg.reset_tier_row_run_registry_for_tests()
    reset_stream_resolution_registry_for_tests()
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
        for _index in range(20):
            other = _session_for_player(sample_turn, player_id=player_id)
            # Distinct run_ids via fresh sessions; mark cancelled then leave retained.
            other_run = RowRun(other)
            reg.register_row_run(other_run)
            reg.mark_row_run_cancelled(other_run.run_id)

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
        assert reg.get_row_run_phase(session.run_id) is None
        assert reg.get_persist_admission(session.run_id) is PersistAdmission.CANCEL_DENY

        ctx = make_analytic_query_context(
            sample_turn,
            TurnAnalyticsOptions(),
            export_services={
                SCORES_ANALYTIC_ID: ScoresExportContext(persistence=persistence),
            },
        )
        row_complete = row_complete_with_summary(
            InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
            summary="cancelled run must not persist despite unrelated churn",
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
        reset_stream_resolution_registry_for_tests()


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


def test_cancel_run_uses_cached_generation_without_orch_lookup(sample_turn, monkeypatch, request):
    """cancel_run must not call execution_generation_for_scope (scheduler→orch nest).

    Fingerprint: generation lookup under the scheduler lock ABBA-deadlocks with an
    orch holder that drains listeners needing the scheduler, and hangs diagnostics
    snapshot on the same orch condition.
    """
    from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.errors import ComputeScopeAbortedError
    from api.compute.orchestrator import ComputeNodeRun
    from api.compute.runtime import get_compute_orchestrator, reset_orchestrators_for_tests
    from api.compute.scope import ComputeScope

    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    reset_orchestrators_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)
    scheduler = InferenceRowScheduler()

    def cleanup() -> None:
        reset_inference_row_scheduler_for_tests()
        reset_tier_row_run_registry_for_tests()
        reset_orchestrators_for_tests()
        reset_compute_worker_pool_for_tests(worker_count=1)

    request.addfinalizer(cleanup)

    turn_number = sample_turn.settings.turn
    player_id = sample_turn.scores[0].ownerid
    scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=628580,
        perspective=1,
        turn=turn_number,
        player_id=player_id,
    )
    session = _session_for_player(sample_turn, player_id=player_id)
    orchestrator = get_compute_orchestrator()
    with orchestrator._condition:
        orchestrator._nodes[scope] = ComputeNodeRun(
            scope=scope,
            dependency_scopes=(),
            state="running",
            execution_generation=7,
        )
    with scheduler._lock:
        scheduler._runs[session.run_id] = scope
        scheduler._execution_generation_by_run_id[session.run_id] = 7

    def forbid_generation_lookup(_scope: ComputeScope) -> int | None:
        raise AssertionError(
            "cancel_run must use cached execution generation; "
            "orchestrator lookup under scheduler lock deadlocks"
        )

    monkeypatch.setattr(orchestrator, "execution_generation_for_scope", forbid_generation_lookup)
    scheduler.cancel_run(session.run_id)

    assert session.run_id not in scheduler._runs
    assert orchestrator.nodes[scope].state == "failed"
    assert isinstance(orchestrator.nodes[scope].error, ComputeScopeAbortedError)

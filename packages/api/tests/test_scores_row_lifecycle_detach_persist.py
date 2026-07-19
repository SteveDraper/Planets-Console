"""Detach / late-persist regressions for scores row-run lifecycle."""

from __future__ import annotations

from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
)
from api.analytics.scores.tier_row_run_registry import get_row_run
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.scores_row_lifecycle_test_helpers import (
    _session_for_player,
)


def test_begin_scope_detach_allows_durable_persist_while_run_still_visible(
    sample_turn,
):
    """Detach must not cancel; DETACHED shell must still admit persist.

    Fingerprint: cancel-on-detach raced with ScoresPersistencePolicy, which skips
    cancelled runs -- durable evidence dropped even though the worker finished a
    RowComplete. Detach must leave DETACHED shell (ALLOW), not cancel admission.
    """
    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.options import TurnAnalyticsOptions
    from api.analytics.scores.compute_orchestration import ScoresPersistencePolicy
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores.tier_row_run_registry import (
        get_persist_admission,
        get_row_run_phase,
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope
    from api.streaming.table_stream.row_run_admission import PersistAdmission, RowRunPhase

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
        assert get_row_run(session.run_id) is row_run
        assert get_row_run_phase(session.run_id) is RowRunPhase.DETACHED
        assert get_persist_admission(session.run_id) is PersistAdmission.ALLOW

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
        assert get_row_run_phase(session.run_id) is None

        # After ALLOW retire, compact cancel admission still DENYs late persist.
        persistence.delete_row(628580, 1, turn_number, player_id)
        cancelled = RowRun(session)
        register_row_run(cancelled)
        from api.analytics.scores.tier_row_run_registry import mark_row_run_cancelled

        mark_row_run_cancelled(cancelled.run_id)
        assert get_persist_admission(cancelled.run_id) is PersistAdmission.CANCEL_DENY
        ScoresPersistencePolicy().persist(
            ctx,
            ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=628580,
                perspective=1,
                turn=turn_number,
                player_id=player_id,
            ),
            {"runId": cancelled.run_id, "rowComplete": row_complete},
        )
        assert persistence.get_row(628580, 1, turn_number, player_id) is None
    finally:
        reset_inference_row_scheduler_for_tests()
        reset_tier_row_run_registry_for_tests()


def test_detach_does_not_apply_lifecycle_cancel(sample_turn):
    """begin_scope detach drops ownership without token or cancel admission."""
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.scores.tier_row_run_registry import (
        get_persist_admission,
        get_row_run_phase,
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope
    from api.streaming.table_stream.row_run_admission import PersistAdmission, RowRunPhase

    reset_inference_row_scheduler_for_tests()
    reset_tier_row_run_registry_for_tests()
    scheduler = InferenceRowScheduler()
    try:
        turn_number = sample_turn.settings.turn
        player_id = sample_turn.scores[0].ownerid
        scope = InferenceStreamScope(
            game_id=628580,
            perspective=1,
            turn_number=turn_number,
        )
        scheduler.begin_scope(scope)
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

        # Same-scope preempt detaches prior stream runs without cancel.
        scheduler.begin_scope(scope)

        assert not session.cancel_token.is_cancelled()
        assert get_persist_admission(session.run_id) is PersistAdmission.ALLOW
        assert get_row_run_phase(session.run_id) is RowRunPhase.DETACHED
        assert session.run_id not in scheduler._runs
    finally:
        reset_inference_row_scheduler_for_tests()
        reset_tier_row_run_registry_for_tests()


def test_row_run_phase_survives_scheduler_remove(sample_turn):
    """Cancel admission and DETACHED shells stay on the registry owner after scheduler drop.

    Same-scope re-register supersedes cancel; cross-scope detach must not.
    """
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.scores.tier_row_run_registry import (
        detach_row_run,
        get_persist_admission,
        get_row_run_phase,
        mark_row_run_cancelled,
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.streaming.table_stream.row_run_admission import PersistAdmission, RowRunPhase

    players = [s.ownerid for s in sample_turn.scores[:2]]
    assert len(players) == 2
    reset_tier_row_run_registry_for_tests()
    try:
        cancelled = RowRun(_session_for_player(sample_turn, player_id=players[0]))
        register_row_run(cancelled)
        mark_row_run_cancelled(cancelled.run_id)
        assert get_row_run_phase(cancelled.run_id) is None
        assert get_persist_admission(cancelled.run_id) is PersistAdmission.CANCEL_DENY

        detached = RowRun(_session_for_player(sample_turn, player_id=players[1]))
        register_row_run(detached)
        detach_row_run(detached.run_id)
        assert get_row_run_phase(detached.run_id) is RowRunPhase.DETACHED
        # Cross-scope detach must not clear another scope's cancelled admission.
        assert get_persist_admission(cancelled.run_id) is PersistAdmission.CANCEL_DENY
    finally:
        reset_tier_row_run_registry_for_tests()


def test_stream_disconnect_detaches_without_cancel_and_allows_persist(sample_turn):
    """Disconnect detaches without cancel admission; finish may persist."""
    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.options import TurnAnalyticsOptions
    from api.analytics.scores.compute_orchestration import ScoresPersistencePolicy
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores.tier_row_run_registry import (
        get_persist_admission,
        get_row_run_phase,
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope
    from api.streaming.table_stream.row_run_admission import PersistAdmission, RowRunPhase

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
        assert get_row_run(session.run_id) is row_run
        assert get_row_run_phase(session.run_id) is RowRunPhase.DETACHED
        assert get_persist_admission(session.run_id) is PersistAdmission.ALLOW
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


def test_unknown_run_id_without_rowrun_or_resolution_refuses_persist(sample_turn):
    """Missing retained RowRun must not write (silent refuse, not raise)."""
    from api.analytics.export_context import make_analytic_query_context
    from api.analytics.options import TurnAnalyticsOptions
    from api.analytics.scores.compute_orchestration import ScoresPersistencePolicy
    from api.analytics.scores.export_services import ScoresExportContext
    from api.analytics.scores.tier_row_run_registry import (
        reset_tier_row_run_registry_for_tests,
    )
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope
    from api.streaming.table_stream.row_stream_resolution_registry import (
        reset_stream_resolution_registry_for_tests,
    )

    reset_tier_row_run_registry_for_tests()
    reset_stream_resolution_registry_for_tests()
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    turn_number = sample_turn.settings.turn
    player_id = sample_turn.scores[0].ownerid
    unknown_run_id = "never-registered-run-id"
    assert get_row_run(unknown_run_id) is None

    ctx = make_analytic_query_context(
        sample_turn,
        TurnAnalyticsOptions(),
        export_services={
            SCORES_ANALYTIC_ID: ScoresExportContext(persistence=persistence),
        },
    )
    row_complete = row_complete_with_summary(
        InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
        summary="unknown run must not persist",
    )
    try:
        ScoresPersistencePolicy().persist(
            ctx,
            ComputeScope(
                analytic_id=SCORES_ANALYTIC_ID,
                game_id=628580,
                perspective=1,
                turn=turn_number,
                player_id=player_id,
            ),
            {"runId": unknown_run_id, "rowComplete": row_complete},
        )
        assert persistence.get_row(628580, 1, turn_number, player_id) is None
    finally:
        reset_tier_row_run_registry_for_tests()
        reset_stream_resolution_registry_for_tests()

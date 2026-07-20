"""Scope preempt / other-turn regressions for scores row-run lifecycle."""

from __future__ import annotations

from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.scores.tier_row_run_registry import get_row_run

from tests.scores_row_lifecycle_test_helpers import (
    _session_for_player,
)


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
    """Switching stream turns preempts the prior turn's runs, not other turns.

    Also covers stream resolution state: a turn-scoped detach must not wipe
    stream resolutions for other-turn rows (background warm) or undo the
    keep-resolution-after-unregister invariant for the detached turn's own row.
    """
    from api.analytics.military_score_inference.row_run import RowRun
    from api.analytics.scores.tier_row_run_registry import (
        get_row_run,
        get_row_run_phase,
        register_row_run,
        reset_tier_row_run_registry_for_tests,
    )
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope
    from api.streaming.table_stream.row_run_admission import RowRunPhase
    from api.streaming.table_stream.row_stream_resolution import (
        RowStreamResolutionState,
        RowStreamResolutionTrigger,
    )
    from api.streaming.table_stream.row_stream_resolution_registry import (
        get_stream_resolution,
        transition_stream_resolution,
    )

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

        transition_stream_resolution(
            prior_session.run_id,
            RowStreamResolutionTrigger.SOFT_PROVISIONAL,
        )
        transition_stream_resolution(
            other_session.run_id,
            RowStreamResolutionTrigger.SOFT_PROVISIONAL,
        )

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
        assert get_row_run_phase(prior_session.run_id) is RowRunPhase.DETACHED

        assert not other_session.cancel_token.is_cancelled()
        assert other_session.run_id in scheduler._runs
        assert get_row_run(other_session.run_id) is not None
        assert get_row_run_phase(other_session.run_id) is RowRunPhase.REGISTERED

        # Other-turn resolution must survive untouched (background warm row).
        other_resolution = get_stream_resolution(other_session.run_id)
        assert other_resolution is not None
        assert other_resolution.state is RowStreamResolutionState.SOFT_PROVISIONAL
        # Detached-turn resolution is kept too, matching _remove_run_locked's
        # keep-resolution-after-unregister invariant (late peer events silenced).
        prior_resolution = get_stream_resolution(prior_session.run_id)
        assert prior_resolution is not None
        assert prior_resolution.state is RowStreamResolutionState.SOFT_PROVISIONAL
    finally:
        reset_inference_row_scheduler_for_tests()
        reset_tier_row_run_registry_for_tests()


def test_begin_scope_prior_turn_preempt_keeps_other_turn_held_submissions(sample_turn):
    """A turn-scoped detach must only drop held submissions for the detached turn."""
    from api.analytics.military_score_inference.inference_stream_teardown import (
        HeldTierSubmission,
    )
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.compute.scope import ComputeScope

    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler()
    try:
        turn_number = sample_turn.settings.turn
        player_id = sample_turn.scores[0].ownerid

        def _held_for_turn(turn: int) -> HeldTierSubmission:
            return HeldTierSubmission(
                stream_token="held-token",
                root_scope=ComputeScope(
                    analytic_id=SCORES_ANALYTIC_ID,
                    game_id=628580,
                    perspective=1,
                    turn=turn,
                    player_id=player_id,
                ),
            )

        scheduler.begin_scope(
            InferenceStreamScope(
                game_id=628580,
                perspective=1,
                turn_number=turn_number,
            )
        )
        prior_held = _held_for_turn(turn_number)
        other_held = _held_for_turn(turn_number + 5)
        with scheduler._lock:
            scheduler._held_initial_submissions = [prior_held, other_held]

        # Switch away from prior turn -- only that turn's held submissions drop.
        scheduler.begin_scope(
            InferenceStreamScope(
                game_id=628580,
                perspective=1,
                turn_number=turn_number + 1,
            )
        )

        assert other_held in scheduler._held_initial_submissions
        assert prior_held not in scheduler._held_initial_submissions
    finally:
        reset_inference_row_scheduler_for_tests()


def test_stream_resolutions_are_fifo_bounded_across_states(monkeypatch):
    """Soft/hard stream resolutions stay FIFO-bounded (persist phase is separate)."""
    from api.streaming.table_stream import row_stream_resolution_registry as resolutions
    from api.streaming.table_stream.row_stream_resolution import (
        RowStreamResolutionState,
        RowStreamResolutionTrigger,
    )

    monkeypatch.setattr(resolutions, "MAX_STREAM_RESOLUTIONS", 3)
    resolutions.reset_stream_resolution_registry_for_tests()
    try:
        for index in range(5):
            resolutions.transition_stream_resolution(
                f"soft-{index}",
                RowStreamResolutionTrigger.SOFT_PROVISIONAL,
            )
        for index in range(5):
            resolutions.transition_stream_resolution(
                f"hard-{index}",
                RowStreamResolutionTrigger.DURABLE_COMPLETE,
            )
        soft_retained = [
            index
            for index in range(5)
            if (
                (r := resolutions.get_stream_resolution(f"soft-{index}")) is not None
                and r.state is RowStreamResolutionState.SOFT_PROVISIONAL
            )
        ]
        hard_retained = [
            index
            for index in range(5)
            if (
                (r := resolutions.get_stream_resolution(f"hard-{index}")) is not None
                and r.state is RowStreamResolutionState.HARD_TERMINAL
            )
        ]
        assert soft_retained == []
        assert hard_retained == [2, 3, 4]
    finally:
        resolutions.reset_stream_resolution_registry_for_tests()

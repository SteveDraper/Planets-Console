"""Tests for accelerated-segment streaming solution admission."""

from __future__ import annotations

from api.analytics.military_score_inference.accelerated_start import (
    ACCEL_WINDOW_SEGMENT_ID,
    REPORTED_HOST_TURN_SEGMENT_ID,
    AcceleratedInferenceSegment,
)
from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_path import InferencePath
from api.analytics.military_score_inference.inference_row_runner import (
    InferenceTierJobCallbacks,
    run_inference_tier_job,
)
from api.analytics.military_score_inference.inference_stream_domain_events import (
    HeldSolutionsUpdated,
)
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import (
    InferenceSolution,
    InferenceSolutionAction,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.transport.inference_stream_wire import domain_event_to_wire_events


def _accel_window_segment() -> AcceleratedInferenceSegment:
    return AcceleratedInferenceSegment(
        segment_id=ACCEL_WINDOW_SEGMENT_ID,
        host_turn=1,
        military_delta_2x=110,
        warship_delta=0,
        freighter_delta=1,
        priority_point_delta=0,
    )


def _reported_host_turn_segment() -> AcceleratedInferenceSegment:
    return AcceleratedInferenceSegment(
        segment_id=REPORTED_HOST_TURN_SEGMENT_ID,
        host_turn=2,
        military_delta_2x=20,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=0,
    )


def _accelerated_split_orchestration(
    sample_turn,
) -> InferenceStreamOrchestration:
    score = sample_turn.scores[0]
    return InferenceStreamOrchestration(
        path=InferencePath.ACCELERATED_SPLIT,
        row_score=score,
        row_turn=sample_turn,
        solve_score=score,
        solve_turn=sample_turn,
        segments=(_accel_window_segment(), _reported_host_turn_segment()),
    )


def test_new_ladder_state_uses_full_k_per_segment(sample_turn) -> None:
    orchestration = _accelerated_split_orchestration(sample_turn)

    assert orchestration.new_ladder_state().resolved_max_solutions == 20


def test_should_emit_streaming_solutions_false_for_accel_window_segment(sample_turn) -> None:
    orchestration = _accelerated_split_orchestration(sample_turn)

    assert orchestration.current_segment().segment_id == ACCEL_WINDOW_SEGMENT_ID
    assert orchestration.should_emit_streaming_solutions() is False


def test_should_emit_streaming_solutions_true_for_reported_host_turn_segment(sample_turn) -> None:
    orchestration = _accelerated_split_orchestration(sample_turn)
    orchestration.current_segment_index = 1

    assert orchestration.current_segment().segment_id == REPORTED_HOST_TURN_SEGMENT_ID
    assert orchestration.should_emit_streaming_solutions() is True


def test_should_emit_streaming_solutions_false_for_backfill_non_target_segment(sample_turn) -> None:
    score = sample_turn.scores[0]
    segments = (
        AcceleratedInferenceSegment(
            segment_id=ACCEL_WINDOW_SEGMENT_ID,
            host_turn=2,
            military_delta_2x=50,
            warship_delta=0,
            freighter_delta=0,
            priority_point_delta=0,
        ),
        AcceleratedInferenceSegment(
            segment_id=REPORTED_HOST_TURN_SEGMENT_ID,
            host_turn=1,
            military_delta_2x=110,
            warship_delta=0,
            freighter_delta=1,
            priority_point_delta=0,
        ),
    )
    orchestration = InferenceStreamOrchestration(
        path=InferencePath.ACCELERATED_BACKFILL,
        row_score=score,
        row_turn=sample_turn,
        solve_score=score,
        solve_turn=sample_turn,
        segments=segments,
        backfill_target_host_turn=1,
        backfill_source_turn_number=3,
    )

    assert orchestration.current_segment().host_turn == 2
    assert orchestration.should_emit_streaming_solutions() is False


def test_run_inference_tier_job_does_not_emit_on_admission_for_accel_window_segment(
    sample_turn,
    monkeypatch,
) -> None:
    orchestration = _accelerated_split_orchestration(sample_turn)
    score = sample_turn.scores[0]
    session = InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    run = RowRun(session)
    run.orchestration = orchestration
    run.ladder_state = orchestration.new_ladder_state()

    solution = InferenceSolution(
        objective_value=20,
        actions=(InferenceSolutionAction(action_id="action_a", label="Action A", count=1),),
    )

    def fake_solve_catalog(
        _observation,
        _catalog,
        *,
        race_id=None,
        max_solutions,
        time_limit_seconds,
        military_score_alpha=0,
        fixed_combo_counts=None,
        combo_count_neighborhood=0,
        cancel_token=None,
        on_solution=None,
    ):
        del race_id, max_solutions, time_limit_seconds, military_score_alpha
        del fixed_combo_counts, combo_count_neighborhood, cancel_token
        if on_solution is not None:
            on_solution(solution)
        from api.analytics.military_score_inference.actions import build_inference_problem

        problem = build_inference_problem(_observation, _catalog, max_solutions=1)
        from api.analytics.military_score_inference.models import InferenceResult

        return (
            InferenceResult(
                status=STATUS_EXACT,
                solutions=(solution,),
                diagnostics={},
            ),
            problem,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step._solve_seed_progression",
        lambda *args, **kwargs: (None, None),
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step._solve_catalog",
        fake_solve_catalog,
    )

    emitted_observations: list[object] = []
    callbacks = InferenceTierJobCallbacks(
        emit_tier_started_progress=lambda: None,
        emit_progress=lambda: None,
        emit_held_solutions=emitted_observations.append,
    )

    run_inference_tier_job(run, callbacks)

    assert emitted_observations == []


def test_run_inference_tier_job_emits_on_admission_for_reported_host_turn_segment(
    sample_turn,
    monkeypatch,
) -> None:
    orchestration = _accelerated_split_orchestration(sample_turn)
    orchestration.current_segment_index = 1
    score = sample_turn.scores[0]
    session = InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    run = RowRun(session)
    run.orchestration = orchestration
    run.ladder_state = orchestration.new_ladder_state()
    observation = orchestration.current_observation()

    solution = InferenceSolution(
        objective_value=20,
        actions=(InferenceSolutionAction(action_id="action_a", label="Action A", count=1),),
    )

    def fake_solve_catalog(
        _observation,
        _catalog,
        *,
        race_id=None,
        max_solutions,
        time_limit_seconds,
        military_score_alpha=0,
        fixed_combo_counts=None,
        combo_count_neighborhood=0,
        cancel_token=None,
        on_solution=None,
    ):
        del race_id, max_solutions, time_limit_seconds, military_score_alpha
        del fixed_combo_counts, combo_count_neighborhood, cancel_token
        if on_solution is not None:
            on_solution(solution)
        from api.analytics.military_score_inference.actions import build_inference_problem

        problem = build_inference_problem(_observation, _catalog, max_solutions=1)
        from api.analytics.military_score_inference.models import InferenceResult

        return (
            InferenceResult(
                status=STATUS_EXACT,
                solutions=(solution,),
                diagnostics={},
            ),
            problem,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step._solve_seed_progression",
        lambda *args, **kwargs: (None, None),
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step._solve_catalog",
        fake_solve_catalog,
    )

    emitted_observations: list[object] = []
    callbacks = InferenceTierJobCallbacks(
        emit_tier_started_progress=lambda: None,
        emit_progress=lambda: None,
        emit_held_solutions=emitted_observations.append,
    )

    run_inference_tier_job(run, callbacks)

    assert len(emitted_observations) == 1
    emitted = emitted_observations[0]
    assert emitted.player_id == observation.player_id
    assert emitted.military_delta_2x == observation.military_delta_2x
    assert emitted.scoreboard_delta_source == "accelerated_segment"


def test_emit_held_solutions_includes_reported_host_turn_segment_id(sample_turn) -> None:
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
        reset_inference_row_scheduler_for_tests,
    )

    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    orchestration = _accelerated_split_orchestration(sample_turn)
    orchestration.current_segment_index = 1
    score = sample_turn.scores[0]
    session = InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    scheduler.enqueue_tier_ladder(session, orchestration=orchestration)
    run = scheduler._runs[session.run_id]
    run.ladder_state.catalog = ActionCatalog((), (), {})
    run.ladder_state.merged_solutions = [
        InferenceSolution(
            objective_value=20,
            actions=(InferenceSolutionAction(action_id="action_a", label="Action A", count=1),),
        )
    ]

    scheduler._emit_held_solutions(
        session,
        observation=orchestration.current_observation(),
    )

    event = session.event_queue.get(timeout=1.0)
    assert isinstance(event, HeldSolutionsUpdated)
    assert event.segment_id == REPORTED_HOST_TURN_SEGMENT_ID

    wire_events = domain_event_to_wire_events(
        event,
        observation=session.observation,
        turn=sample_turn,
    )
    wire = wire_events[0]
    assert wire["segmentId"] == REPORTED_HOST_TURN_SEGMENT_ID
    assert "isTargetSegment" not in wire

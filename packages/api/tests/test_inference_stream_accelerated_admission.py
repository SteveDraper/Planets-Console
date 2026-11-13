"""Tests for accelerated-segment streaming solution admission."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.accelerated_start import (
    ACCEL_WINDOW_SEGMENT_ID,
    REPORTED_HOST_TURN_SEGMENT_ID,
    AcceleratedInferenceSegment,
)
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_accelerated import (
    build_accelerated_backfill_stream_row_complete,
)
from api.analytics.military_score_inference.inference_admission import (
    admission_skip_for_status,
)
from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_NO_PRIOR_TURN,
)
from api.analytics.military_score_inference.inference_path import InferencePath
from api.analytics.military_score_inference.inference_row_runner import (
    InferenceTierJobCallbacks,
    run_inference_tier_job,
    stream_row_search_effort_allowance,
)
from api.analytics.military_score_inference.inference_stream_domain_events import (
    HeldSolutionsUpdated,
)
from api.analytics.military_score_inference.inference_stream_orchestration import (
    InferenceStreamOrchestration,
    new_ladder_state,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import (
    InferenceSolution,
    InferenceSolutionAction,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.transport.inference_stream_wire import (
    domain_event_to_wire_events,
    row_complete_to_complete_wire_event,
)


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


def test_new_ladder_state_uses_full_k_per_segment() -> None:
    assert new_ladder_state().resolved_max_solutions == 20


def test_new_ladder_state_builds_hopeless_facts_from_session(sample_turn) -> None:
    score = sample_turn.scores[0]
    session = InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    state = new_ladder_state(session)
    assert state.hopeless_context is not None
    assert state.hopeless_context.planet_delta == score.planetchange
    assert state.hopeless_context.starbase_delta == score.starbasechange


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


def _admit_one_solution_during_a_tier(
    sample_turn,
    monkeypatch,
    *,
    segment_index: int,
) -> tuple[InferenceRowStreamSession, InferenceStreamOrchestration]:
    """Run one accelerated tier through the scheduler's callbacks; the solve admits one solution."""
    from api.analytics.military_score_inference.inference_scheduler import (
        InferenceRowScheduler,
        reset_inference_row_scheduler_for_tests,
    )
    from api.analytics.scores.tier_row_run_registry import get_row_run, get_tier_callbacks

    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=0)
    scheduler.begin_scope(
        InferenceStreamScope(
            game_id=628580,
            perspective=1,
            turn_number=sample_turn.settings.turn,
        )
    )
    orchestration = _accelerated_split_orchestration(sample_turn)
    orchestration.current_segment_index = segment_index
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
    run = get_row_run(session.run_id)
    assert run is not None
    run.ladder_state = new_ladder_state()

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
        solve_clip,
        military_score_window=None,
        pins=None,
        cancel_token=None,
        on_solution=None,
        seed_no_good_solutions=(),
        **_budget,
    ):
        del race_id, max_solutions, solve_clip, military_score_window
        del pins, cancel_token, seed_no_good_solutions
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

    callbacks = get_tier_callbacks(session.run_id)
    assert callbacks is not None
    run_inference_tier_job(run, callbacks)
    return session, orchestration


def _queued_held_solutions(session: InferenceRowStreamSession) -> list[HeldSolutionsUpdated]:
    held: list[HeldSolutionsUpdated] = []
    while not session.event_queue.empty():
        event = session.event_queue.get_nowait()
        if isinstance(event, HeldSolutionsUpdated):
            held.append(event)
    return held


def test_an_admission_in_the_accel_window_segment_streams_no_held_solutions(
    sample_turn,
    monkeypatch,
) -> None:
    session, _orchestration = _admit_one_solution_during_a_tier(
        sample_turn, monkeypatch, segment_index=0
    )

    assert _queued_held_solutions(session) == []


def test_an_admission_in_the_reported_host_turn_segment_streams_its_held_solutions(
    sample_turn,
    monkeypatch,
) -> None:
    session, orchestration = _admit_one_solution_during_a_tier(
        sample_turn, monkeypatch, segment_index=1
    )

    held = _queued_held_solutions(session)
    assert len(held) == 1
    event = held[0]
    observation = orchestration.current_observation()
    assert event.observation.player_id == observation.player_id
    assert event.observation.military_delta_2x == observation.military_delta_2x
    assert event.observation.scoreboard_delta_source == "accelerated_segment"
    assert event.segment_id == REPORTED_HOST_TURN_SEGMENT_ID

    wire_events = domain_event_to_wire_events(
        event,
        observation=session.observation,
        turn=sample_turn,
    )
    wire = wire_events[0]
    assert wire["segmentId"] == REPORTED_HOST_TURN_SEGMENT_ID
    assert "isTargetSegment" not in wire


def test_run_inference_tier_job_uses_stream_tier_time_budget(sample_turn, monkeypatch) -> None:
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
    run.ladder_state = new_ladder_state()

    captured: list[float | None] = []

    def fake_tier_step(
        state,
        observation,
        turn,
        *,
        time_limit_seconds=None,
        cancel_token=None,
        on_admitted=None,
        search_effort_allowance=None,
        hang_fuse_seconds=None,
    ) -> None:
        del state, observation, turn, time_limit_seconds, cancel_token, on_admitted
        del hang_fuse_seconds
        captured.append(search_effort_allowance)
        run.ladder_state.ladder_complete = True

    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_row_runner.run_policy_ladder_tier_step",
        fake_tier_step,
    )

    callbacks = InferenceTierJobCallbacks(
        emit_tier_started_progress=lambda: None,
        emit_progress=lambda: None,
        emit_held_solutions=lambda: None,
    )
    run_inference_tier_job(run, callbacks)

    assert captured == [stream_row_search_effort_allowance()]


def _hull_mask(*hull_ids: int) -> ResolvedHullCatalogMask:
    enabled = frozenset(hull_ids)
    return ResolvedHullCatalogMask(
        race_id=0,
        race_name="test",
        master_hull_ids=enabled,
        default_enabled_hull_ids=enabled,
        effective_enabled_hull_ids=enabled,
        has_user_override=True,
    )


@pytest.mark.parametrize("ladder_mask", [_hull_mask(1, 2), None])
def test_segment_continuation_keeps_the_ladder_state_mask(
    sample_turn, monkeypatch, ladder_mask
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
        resolved_mask=ladder_mask,
    )
    run = RowRun(session)
    run.orchestration = orchestration
    run.ladder_state = new_ladder_state(session)

    def fake_tier_step(state, *_args, **_kwargs) -> None:
        session.resolved_mask = _hull_mask(3)
        state.ladder_complete = True

    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_row_runner.run_policy_ladder_tier_step",
        fake_tier_step,
    )

    outcome = run_inference_tier_job(
        run,
        InferenceTierJobCallbacks(
            emit_tier_started_progress=lambda: None,
            emit_progress=lambda: None,
            emit_held_solutions=lambda: None,
        ),
    )

    assert outcome.enqueue_continuation is True
    assert outcome.next_ladder_state is not None
    assert outcome.next_ladder_state.resolved_mask is ladder_mask
    assert run.ladder_state is outcome.next_ladder_state


def test_accelerated_backfill_unavailable_stream_skip_has_no_diagnostics(sample_turn) -> None:
    score = next(row for row in sample_turn.scores if row.ownerid != sample_turn.player.id)
    complete = build_accelerated_backfill_stream_row_complete(
        score,
        sample_turn,
        target_host_turn=1,
        source_turn_number=3,
        source_turn=sample_turn,
        segment_solves=(),
    )
    skip = admission_skip_for_status(STATUS_NO_PRIOR_TURN)
    assert complete.wire_payload.status == skip.status
    assert complete.wire_payload.summary == skip.summary
    assert complete.wire_payload.diagnostics is None
    event = row_complete_to_complete_wire_event(complete)
    assert "diagnostics" not in event

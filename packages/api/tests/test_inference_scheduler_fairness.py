"""Tests for cross-row fairness in the inference row scheduler."""

from __future__ import annotations

import threading
import time

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    _TierJob,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies


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


def test_tier_one_jobs_run_before_continuations_from_other_rows(sample_turn, monkeypatch):
    """A later row's tier-1 job must not wait behind an earlier row's tier-2+ jobs."""
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=1)
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    scheduler.begin_scope(scope)

    execution_order: list[tuple[int, int]] = []
    gate = threading.Event()
    gate.set()

    def fake_tier_step(
        state: PolicyLadderState,
        observation,
        turn,
        *,
        time_limit_seconds=None,
        cancel_token=None,
        on_admitted=None,
    ) -> None:
        player_id = observation.player_id
        step_index = state.next_step_index
        execution_order.append((player_id, step_index))
        state.policy_steps_attempted.append(state.policy_steps[step_index].id)
        state.next_step_index += 1
        if state.next_step_index >= len(state.policy_steps):
            state.ladder_complete = True
        gate.wait(timeout=1.0)

    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_row_runner.run_policy_ladder_tier_step",
        fake_tier_step,
    )
    monkeypatch.setattr(
        scheduler,
        "_emit_row_complete",
        lambda session, _event: scheduler.unregister_session(session.run_id),
    )
    player_ids = [row.ownerid for row in sample_turn.scores[:2]]
    assert len(player_ids) >= 2
    session_a = _session_for_player(sample_turn, player_id=player_ids[0])
    session_b = _session_for_player(sample_turn, player_id=player_ids[1])

    scheduler.enqueue_tier_ladder(session_a)
    gate.clear()
    time.sleep(0.05)
    scheduler.enqueue_tier_ladder(session_b)
    gate.set()

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if len(execution_order) >= 3:
            break
        time.sleep(0.01)

    assert execution_order[:3] == [
        (player_ids[0], 0),
        (player_ids[1], 0),
        (player_ids[0], 1),
    ]


def test_continuation_jobs_round_robin_across_rows(sample_turn, monkeypatch):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler(worker_count=1)
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    scheduler.begin_scope(scope)

    execution_order: list[tuple[int, int]] = []
    gate = threading.Event()
    gate.set()
    short_ladder = resolve_tier_policies(None)[:3]

    def fake_tier_step(
        state: PolicyLadderState,
        observation,
        turn,
        *,
        time_limit_seconds=None,
        cancel_token=None,
        on_admitted=None,
    ) -> None:
        player_id = observation.player_id
        step_index = state.next_step_index
        execution_order.append((player_id, step_index))
        state.policy_steps_attempted.append(state.policy_steps[step_index].id)
        state.next_step_index += 1
        if state.next_step_index >= len(state.policy_steps):
            state.ladder_complete = True
        gate.wait(timeout=1.0)

    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_row_runner.run_policy_ladder_tier_step",
        fake_tier_step,
    )
    monkeypatch.setattr(
        scheduler,
        "_emit_row_complete",
        lambda session, _event: scheduler.unregister_session(session.run_id),
    )

    player_ids = [row.ownerid for row in sample_turn.scores[:2]]
    session_a = _session_for_player(sample_turn, player_id=player_ids[0])
    session_b = _session_for_player(sample_turn, player_id=player_ids[1])
    scheduler.register_session(session_a)
    scheduler.register_session(session_b)
    scheduler._runs[session_a.run_id].ladder_state = PolicyLadderState(
        policy_steps=short_ladder,
    )
    scheduler._runs[session_b.run_id].ladder_state = PolicyLadderState(
        policy_steps=short_ladder,
    )
    scheduler._enqueue_job(_TierJob(session=session_a))
    scheduler._enqueue_job(_TierJob(session=session_b))
    gate.set()

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if len(execution_order) >= 4:
            break
        time.sleep(0.01)

    assert execution_order[:4] == [
        (player_ids[0], 0),
        (player_ids[1], 0),
        (player_ids[0], 1),
        (player_ids[1], 1),
    ]

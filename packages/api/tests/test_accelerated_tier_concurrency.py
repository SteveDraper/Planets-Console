"""Regression: accelerated tier jobs must not raise under concurrent dispatch."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_row_runner import (
    InferenceTierJobCallbacks,
    TierJobRowComplete,
    run_inference_tier_job,
    solve_context,
)
from api.analytics.military_score_inference.inference_stream_orchestration import (
    new_ladder_state,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores.tier_row_run_registry import new_tier_row_run

from tests.accelerated_segment_helpers import accelerated_split_orchestration


def _stub_instant_ladder(monkeypatch) -> None:
    def instant_complete(state, observation, turn, **kwargs):
        del observation, turn, kwargs
        state.ladder_complete = True
        state.catalog = None

    def fake_finalize(state, observation, turn):
        del state, observation, turn
        result = InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={})
        return result, None, None, [], []

    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_row_runner.run_policy_ladder_tier_step",
        instant_complete,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_stream_orchestration.finalize_policy_ladder_result",
        fake_finalize,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_row_runner.finalize_policy_ladder_result",
        fake_finalize,
    )


def test_concurrent_shared_rowrun_accelerated_completes_without_raise(
    sample_turn,
    monkeypatch,
) -> None:
    """Duplicate concurrent tier_solve on one RowRun must serialize and complete."""
    _stub_instant_ladder(monkeypatch)
    score = sample_turn.scores[0]
    orchestration = accelerated_split_orchestration(sample_turn, sample_turn.scores[0])
    session = InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=1,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    run = new_tier_row_run(session)
    run.ladder = replace(run.ladder, orchestration=orchestration)
    run.ladder = replace(run.ladder, ladder_state=new_ladder_state())

    callbacks = InferenceTierJobCallbacks(
        emit_tier_started_progress=lambda: None,
        emit_progress=lambda: None,
        emit_held_solutions=lambda: None,
    )
    errors: list[str] = []
    terminals = 0
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def worker() -> None:
        nonlocal terminals
        try:
            barrier.wait()
            for _ in range(30):
                outcome = run_inference_tier_job(run, callbacks)
                if isinstance(outcome, TierJobRowComplete):
                    with lock:
                        terminals += 1
                    break
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker), pool.submit(worker)]
        for future in futures:
            future.result()

    assert not errors, errors
    assert terminals >= 1
    assert orchestration.current_segment() is None
    assert len(orchestration.segment_solves) >= 1


def test_solve_context_raises_when_segments_exhausted(sample_turn) -> None:
    score = sample_turn.scores[0]
    orchestration = accelerated_split_orchestration(sample_turn, sample_turn.scores[0])
    orchestration.current_segment_index = len(orchestration.segments)
    session = InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=1,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    run = new_tier_row_run(session)
    run.ladder = replace(run.ladder, orchestration=orchestration)
    run.ladder = replace(run.ladder, ladder_state=new_ladder_state())

    try:
        solve_context(run)
    except RuntimeError as exc:
        assert "no active segment" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for exhausted segments")


def test_run_inference_tier_job_idempotent_when_segments_exhausted(
    sample_turn,
    monkeypatch,
) -> None:
    _stub_instant_ladder(monkeypatch)
    score = sample_turn.scores[0]
    orchestration = accelerated_split_orchestration(sample_turn, sample_turn.scores[0])
    orchestration.current_segment_index = len(orchestration.segments)
    session = InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=1,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    run = new_tier_row_run(session)
    run.ladder = replace(run.ladder, orchestration=orchestration)
    run.ladder = replace(run.ladder, ladder_state=new_ladder_state())
    callbacks = InferenceTierJobCallbacks(
        emit_tier_started_progress=lambda: None,
        emit_progress=lambda: None,
        emit_held_solutions=lambda: None,
    )

    outcome = run_inference_tier_job(run, callbacks)
    assert isinstance(outcome, TierJobRowComplete)

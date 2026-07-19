"""Tests for global pause/resume on the inference row scheduler."""

import pytest
from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_domain_events import (
    HeldSolutionsUpdated,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceSolution, InferenceSolutionAction
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.analytics.scores.tier_row_run_registry import get_row_run
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeNodeRun
from api.compute.scope import ComputeScope
from api.errors import ValidationError


@pytest.fixture(autouse=True)
def noop_orchestrator_tier_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        InferenceRowScheduler,
        "_submit_tier_solve_locked",
        lambda self, binding, root_scope: None,
    )


def _session_for_turn(
    sample_turn,
    *,
    game_id: int = 628580,
    perspective: int = 1,
) -> InferenceRowStreamSession:
    score = sample_turn.scores[0]
    return InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=game_id,
        perspective=perspective,
        turn_number=sample_turn.settings.turn,
    )


def test_pause_without_active_stream_raises_validation_error(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler()
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )

    with pytest.raises(ValidationError, match="active inference table stream"):
        scheduler.pause_globally(scope)

    with pytest.raises(ValidationError, match="active inference table stream"):
        scheduler.resume_globally(scope)


def test_pause_with_mismatched_scope_raises_validation_error(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler()
    scope_a = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    scope_b = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn + 1,
    )
    scheduler.begin_scope(scope_a)

    with pytest.raises(ValidationError, match="active inference table stream"):
        scheduler.pause_globally(scope_b)

    with pytest.raises(ValidationError, match="active inference table stream"):
        scheduler.resume_globally(scope_b)


def test_pause_counts_gated_orchestrator_continuation(sample_turn):
    """Continuations held while paused are ready orchestrator nodes with step_index > 0."""
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler()
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    stream_token = scheduler.begin_scope(scope)
    session = _session_for_turn(sample_turn)
    scheduler.enqueue_tier_ladder(session, stream_token=stream_token)

    root_scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=session.game_id,
        perspective=session.perspective,
        turn=session.turn_number,
        player_id=session.player_id,
    )

    class FakeOrchestrator:
        def __init__(self) -> None:
            self.nodes = {
                root_scope: ComputeNodeRun(
                    scope=root_scope,
                    dependency_scopes=(),
                    state="ready",
                    step_index=1,
                    profile_step_index=1,
                )
            }
            self.dispatch_calls = 0
            self.observers = type(
                "FakeObservers",
                (),
                {"register_dispatch_gate": lambda _self, _gate: lambda: None},
            )()

        def peek_ready_step_indexes(self, scopes: tuple) -> dict:
            return {
                scope: node.step_index
                for scope, node in self.nodes.items()
                if scope in scopes and node.state == "ready"
            }

        def dispatch_ready_work(self) -> None:
            self.dispatch_calls += 1

    fake_orchestrator = FakeOrchestrator()
    scheduler._stream_bindings[stream_token] = type(
        "FakeBinding",
        (),
        {
            "orchestrator": fake_orchestrator,
            "unregister_dispatch_gate": None,
            "query_context": object(),
        },
    )()

    scheduler.pause_globally(scope)

    status = scheduler.global_pause_status(scope)
    assert status["heldContinuationCount"] == 1
    assert status["heldJobCount"] == 0

    resumed = scheduler.resume_globally(scope)
    assert resumed["heldContinuationCount"] == 0
    assert fake_orchestrator.dispatch_calls == 1


def test_pause_holds_enqueued_jobs_and_resume_requeues(sample_turn, monkeypatch):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler()
    submitted_scopes: list[object] = []

    def record_submit(
        self,
        binding: object,
        root_scope: object,
    ) -> None:
        submitted_scopes.append(root_scope)

    monkeypatch.setattr(InferenceRowScheduler, "_submit_tier_solve_locked", record_submit)
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    scheduler.begin_scope(scope)
    session = _session_for_turn(sample_turn)
    scheduler.pause_globally(scope)
    scheduler.enqueue_tier_ladder(session)

    paused = scheduler.global_pause_status(scope)
    assert paused["paused"] is True
    assert paused["heldJobCount"] == 1
    assert submitted_scopes == []

    status = scheduler.global_pause_status(scope)
    assert status["paused"] is True

    resumed = scheduler.resume_globally(scope)
    assert resumed["paused"] is False
    assert resumed["heldJobCount"] == 0
    assert len(submitted_scopes) == 1


def test_resume_dispatches_orchestrator_ready_work(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler()
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    stream_token = scheduler.begin_scope(scope)

    class FakeOrchestrator:
        nodes = {}

        def __init__(self) -> None:
            self.dispatch_calls = 0
            self.observers = type(
                "FakeObservers",
                (),
                {"register_dispatch_gate": lambda _self, _gate: lambda: None},
            )()

        def peek_ready_step_indexes(self, scopes: tuple) -> dict:
            return {}

        def dispatch_ready_work(self) -> None:
            self.dispatch_calls += 1

    fake_orchestrator = FakeOrchestrator()
    fake_binding = type(
        "FakeBinding",
        (),
        {
            "orchestrator": fake_orchestrator,
            "unregister_dispatch_gate": None,
            "query_context": object(),
        },
    )()
    scheduler._stream_bindings[stream_token] = fake_binding
    scheduler.pause_globally(scope)

    scheduler.resume_globally(scope)

    assert fake_orchestrator.dispatch_calls == 1


def test_new_scope_invalidates_retained_pause_state(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler()
    scope_a = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    scope_b = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn + 1,
    )
    scheduler.begin_scope(scope_a)
    scheduler.pause_globally(scope_a)
    scheduler.begin_scope(scope_b)

    status = scheduler.global_pause_status(scope_a)
    assert status["paused"] is False
    assert status["activeScope"]["turn"] == scope_b.turn_number


def test_begin_scope_preempts_stale_stream_for_same_scope(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler()
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    session = _session_for_turn(sample_turn)
    first_token = scheduler.begin_scope(scope)
    scheduler.enqueue_tier_ladder(session)

    second_token = scheduler.begin_scope(scope)

    assert second_token != first_token
    assert not scheduler.owns_table_stream(first_token)
    assert scheduler.owns_table_stream(second_token)
    # Detach drops stream ownership without cancelling in-flight solve work.
    assert not session.cancel_token.is_cancelled()
    assert session.run_id not in scheduler._runs
    status = scheduler.global_pause_status(scope)
    assert status["activeSessionCount"] == 0


def test_begin_scope_succeeds_after_detach_inference_stream(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler()
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    session = _session_for_turn(sample_turn)
    stream_token = scheduler.begin_scope(scope)
    scheduler.enqueue_tier_ladder(session)
    scheduler.detach_inference_stream(scope, (session,), stream_token=stream_token)

    scheduler.begin_scope(scope)

    status = scheduler.global_pause_status(scope)
    assert status["activeSessionCount"] == 0
    assert status["paused"] is False


def test_detach_inference_stream_leaves_runs_running_and_clears_global_pause(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler()
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    session = _session_for_turn(sample_turn)
    stream_token = scheduler.begin_scope(scope)
    scheduler.enqueue_tier_ladder(session)
    scheduler.pause_globally(scope)

    assert scheduler.global_pause_status(scope)["paused"] is True
    assert scheduler.global_pause_status(scope)["activeSessionCount"] == 1

    scheduler.detach_inference_stream(scope, (session,), stream_token=stream_token)

    status = scheduler.global_pause_status(scope)
    assert status["paused"] is False
    assert status["activeSessionCount"] == 0
    assert status["heldJobCount"] == 0
    assert not session.cancel_token.is_cancelled()


def test_stale_detach_inference_stream_does_not_clear_replacement_stream(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler()
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    old_session = _session_for_turn(sample_turn)
    old_token = scheduler.begin_scope(scope)
    scheduler.enqueue_tier_ladder(old_session)

    new_session = _session_for_turn(sample_turn)
    new_token = "replacement-stream-token"
    scheduler._scope_guard._active_table_stream_token = new_token
    scheduler._scope_guard._has_active_table_stream = True
    scheduler.enqueue_tier_ladder(new_session)

    scheduler.detach_inference_stream(scope, (old_session,), stream_token=old_token)

    status = scheduler.global_pause_status(scope)
    assert status["activeSessionCount"] == 1
    assert scheduler._scope_guard.has_active_table_stream is True
    assert not old_session.cancel_token.is_cancelled()
    assert not new_session.cancel_token.is_cancelled()

    scheduler.detach_inference_stream(scope, (new_session,), stream_token=new_token)
    assert scheduler.global_pause_status(scope)["activeSessionCount"] == 0


def test_emit_held_solutions_snapshots_merged_list(sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler()
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    scheduler.begin_scope(scope)
    session = _session_for_turn(sample_turn)
    scheduler.enqueue_tier_ladder(session)
    row_run = get_row_run(session.run_id)
    assert row_run is not None
    row_run.ladder_state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    row_run.ladder_state.catalog = ActionCatalog((), (), {})
    row_run.ladder_state.merged_solutions = [
        InferenceSolution(
            objective_value=10,
            actions=(InferenceSolutionAction(action_id="a1", label="Action A", count=1),),
        )
    ]

    scheduler._emit_held_solutions(session, observation=session.observation)

    event = session.event_queue.get(timeout=1.0)
    assert isinstance(event, HeldSolutionsUpdated)
    assert len(event.solutions) == 1
    assert event.solutions[0].objective_value == 10

    row_run.ladder_state.merged_solutions.append(
        InferenceSolution(
            objective_value=5,
            actions=(InferenceSolutionAction(action_id="a2", label="Action B", count=1),),
        )
    )

    assert len(event.solutions) == 1
    assert event.solutions[0].objective_value == 10

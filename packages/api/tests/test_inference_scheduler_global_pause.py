"""Tests for global pause/resume on the inference row scheduler."""

from dataclasses import replace

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
from api.analytics.military_score_inference.inference_stream_scope import (
    InferenceStreamScope,
    scores_root_scope_for_session,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceSolution, InferenceSolutionAction
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.analytics.scores.compute_orchestration import SCORES_TIER_SOLVE
from api.analytics.scores.tier_row_run_registry import get_row_run
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeNodeRun
from api.compute.orchestrator_state import ComputeRequest
from api.compute.pools import reset_compute_worker_pool_for_tests
from api.compute.runtime import get_compute_orchestrator
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.errors import ValidationError

from tests.scores_exports_helpers import (
    minimal_stream_query_context,
    scores_query_context,
    stream_scope_for_turn,
)
from tests.scores_row_lifecycle_test_helpers import _patch_scores_dag_without_fleet_deps


@pytest.fixture(autouse=True)
def noop_orchestrator_tier_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        InferenceRowScheduler,
        "_submit_tier_solve",
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
        query_context=minimal_stream_query_context(
            sample_turn,
            game_id=game_id,
            perspective=perspective,
        ),
    )


def _count_process_dispatch_passes(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count dispatch passes on the process orchestrator, where the pause gate is registered."""
    orchestrator = get_compute_orchestrator()
    calls = [0]
    real_dispatch = orchestrator.dispatch_ready_work

    def count_dispatch() -> None:
        calls[0] += 1
        real_dispatch()

    monkeypatch.setattr(orchestrator, "dispatch_ready_work", count_dispatch)
    return calls


def test_cancel_before_accept_does_not_submit(sample_turn, monkeypatch) -> None:
    reset_inference_row_scheduler_for_tests()
    scheduler = InferenceRowScheduler()
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    stream_token = scheduler.begin_scope(scope)
    submitted: list[object] = []

    def record_submit(self, binding, root_scope) -> None:
        del self, binding
        submitted.append(root_scope)

    monkeypatch.setattr(InferenceRowScheduler, "_submit_tier_solve", record_submit)

    cancelled = _session_for_turn(sample_turn)
    scheduler.enqueue_tier_ladder(cancelled, stream_token=stream_token)
    assert submitted == []
    scheduler.cancel_row_run(cancelled.run_id)
    scheduler.accept_pending_run(cancelled.run_id)
    assert submitted == []

    live = _session_for_turn(sample_turn)
    scheduler.enqueue_tier_ladder(live, stream_token=stream_token)
    scheduler.accept_pending_run(live.run_id)
    assert submitted == [scores_root_scope_for_session(live)]


def test_pause_without_active_stream_raises_validation_error(make_inference_scheduler, sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = make_inference_scheduler()
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )

    with pytest.raises(ValidationError, match="active inference table stream"):
        scheduler.pause_globally(scope)

    with pytest.raises(ValidationError, match="active inference table stream"):
        scheduler.resume_globally(scope)


def test_pause_with_mismatched_scope_raises_validation_error(make_inference_scheduler, sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = make_inference_scheduler()
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


def test_pause_counts_gated_orchestrator_continuation(
    make_inference_scheduler, sample_turn, monkeypatch
):
    """Continuations held while paused are ready orchestrator nodes with step_index > 0."""
    reset_inference_row_scheduler_for_tests()
    scheduler = make_inference_scheduler()
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
                    submission_open=SubmissionOpen(),
                )
            }

            self.dispatch_passes = 0

        def peek_ready_step_indexes(self, scopes: tuple) -> dict:
            return {
                scope: node.step_index
                for scope, node in self.nodes.items()
                if scope in scopes and node.state == "ready"
            }

        def dispatch_ready_work(self) -> None:
            self.dispatch_passes += 1

    fake_orchestrator = FakeOrchestrator()
    scheduler.pause_globally(scope)
    # Held counts read the orchestrator the pause gate is registered on.
    monkeypatch.setattr(
        scheduler._orchestrator_attachment,
        "registered_orchestrator",
        lambda: fake_orchestrator,
    )

    status = scheduler.global_pause_status(scope)
    assert status["heldContinuationCount"] == 1
    assert status["heldJobCount"] == 0

    resumed = scheduler.resume_globally(scope)
    assert resumed["heldContinuationCount"] == 0
    assert fake_orchestrator.dispatch_passes == 1


def test_resume_runs_a_dispatch_pass_on_the_pause_gate_orchestrator(
    make_inference_scheduler, sample_turn, monkeypatch
):
    reset_inference_row_scheduler_for_tests()
    scheduler = make_inference_scheduler()
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)
    dispatch_calls = _count_process_dispatch_passes(monkeypatch)

    scheduler.resume_globally(scope)

    assert dispatch_calls == [1]


def test_resume_commits_every_tier_solve_the_pause_gate_held_in_its_one_pass(
    make_inference_scheduler, sample_turn, persistence, monkeypatch
):
    reset_inference_row_scheduler_for_tests()
    pool = reset_compute_worker_pool_for_tests(worker_count=0)
    _patch_scores_dag_without_fleet_deps(monkeypatch)
    scheduler = make_inference_scheduler()
    scope = stream_scope_for_turn(sample_turn)
    scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)
    orchestrator = get_compute_orchestrator()
    ctx = scores_query_context(sample_turn, persistence=persistence, scheduler=scheduler)
    held = tuple(
        ComputeScope(
            analytic_id=SCORES_ANALYTIC_ID,
            game_id=scope.game_id,
            perspective=scope.perspective,
            turn=scope.turn_number,
            player_id=row.ownerid,
        )
        for row in sample_turn.scores
    )
    assert len(held) > 2
    for root_scope in held:
        orchestrator.submit(ComputeRequest(ctx=ctx, scope=root_scope, step_kind=SCORES_TIER_SOLVE))
    assert set(orchestrator.ready_scopes()) == set(held)
    assert pool.snapshot_work_queue() == ()
    dispatch_calls = _count_process_dispatch_passes(monkeypatch)

    scheduler.resume_globally(scope)

    assert dispatch_calls == [1]
    assert orchestrator.ready_scopes() == ()
    assert all(orchestrator.nodes[root_scope].state == "running" for root_scope in held)
    assert {queued.item.scope for queued in pool.snapshot_work_queue()} == set(held)


def test_new_scope_invalidates_retained_pause_state(make_inference_scheduler, sample_turn):
    reset_inference_row_scheduler_for_tests()
    scheduler = make_inference_scheduler()
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
    scheduler.enqueue_tier_ladder(session, stream_token=first_token)

    second_token = scheduler.begin_scope(scope)

    assert second_token != first_token
    assert not scheduler.owns_table_stream(first_token)
    assert scheduler.owns_table_stream(second_token)
    # The preempted stream's rows stay until that stream's own end detaches them.
    assert scheduler.global_pause_status(scope)["activeSessionCount"] == 1

    scheduler.detach_inference_stream(scope, (session,), stream_token=first_token)
    assert not session.cancel_token.is_cancelled()
    assert session.run_id not in scheduler._runs
    assert scheduler.global_pause_status(scope)["activeSessionCount"] == 0


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
    scheduler.enqueue_tier_ladder(session, stream_token=stream_token)
    scheduler.detach_inference_stream(scope, (session,), stream_token=stream_token)

    scheduler.begin_scope(scope)

    status = scheduler.global_pause_status(scope)
    assert status["activeSessionCount"] == 0
    assert status["paused"] is False


def test_detach_inference_stream_leaves_runs_running_and_clears_global_pause(
    make_inference_scheduler, sample_turn
):
    reset_inference_row_scheduler_for_tests()
    scheduler = make_inference_scheduler()
    scope = InferenceStreamScope(
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
    )
    session = _session_for_turn(sample_turn)
    stream_token = scheduler.begin_scope(scope)
    scheduler.enqueue_tier_ladder(session, stream_token=stream_token)
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
    scheduler.enqueue_tier_ladder(old_session, stream_token=old_token)

    new_session = _session_for_turn(sample_turn)
    new_token = "replacement-stream-token"
    scheduler._scope_guard._active_table_stream_token = new_token
    scheduler._scope_guard._has_active_table_stream = True
    scheduler.enqueue_tier_ladder(new_session, stream_token=new_token)

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
    row_run.ladder = replace(
        row_run.ladder,
        ladder_state=PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1])),
    )
    row_run.ladder.ladder_state.catalog = ActionCatalog((), (), {})
    row_run.ladder.ladder_state.merged_solutions = [
        InferenceSolution(
            objective_value=10,
            actions=(InferenceSolutionAction(action_id="a1", label="Action A", count=1),),
        )
    ]

    scheduler._emit_held_solutions(session)

    event = session.event_queue.get(timeout=1.0)
    assert isinstance(event, HeldSolutionsUpdated)
    assert len(event.solutions) == 1
    assert event.solutions[0].objective_value == 10

    row_run.ladder.ladder_state.merged_solutions.append(
        InferenceSolution(
            objective_value=5,
            actions=(InferenceSolutionAction(action_id="a2", label="Action B", count=1),),
        )
    )

    assert len(event.solutions) == 1
    assert event.solutions[0].objective_value == 10

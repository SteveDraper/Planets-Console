"""An aborted scores execution cancels the RowRun its tier-ladder stamp names.

When a scores node execution ends by abort (``ComputeScopeAbortedError``), the
scope-outcome listener applies ``CANCEL`` to the run the scope's ladder stamp
names for that execution, in place of the plain stamp release: the session
token is cancelled, so a running solver stops, and ``CANCEL_DENY`` refuses the
run's late persist. A stamp written for a newer execution is left alone, and a
tier wire build for an execution that has already ended claims nothing.

The orchestrator tests run the real scores ``tier_solve`` wire builder on a
pool that never runs work (``ShellLadder``); the scores listener is attached to
that orchestrator only where a test needs it to run on abort.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest
from api.analytics.military_score_inference.inference_row_runner import (
    TierJobContinue,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceRowScope
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.scores import tier_row_run_registry
from api.analytics.scores.compute_orchestration import SCORES_PERSISTENCE_POLICY
from api.analytics.scores.row_lifecycle import apply_scores_row_lifecycle
from api.analytics.scores.tier_row_run_registry import (
    ScopeIndexPolicy,
    StampedLadderRun,
    TierLadderStamp,
    claim_tier_ladder,
    decide_scores_row_persist,
    get_persist_admission,
    get_row_run,
    get_row_run_phase,
    new_tier_row_run,
    register_row_run,
)
from api.compute import ComputeScope
from api.compute.errors import ComputeExecutionEndedError, ComputeScopeAbortedError
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.streaming.table_stream.row_run_admission import (
    PersistAdmission,
    RowLifecycleOp,
    RowRunPhase,
)

from tests.scores_exports_helpers import inference_target_player_id
from tests.scores_ladder_helpers import (
    ShellLadder,
    durable_row_complete,
    ladder_scope,
    ladder_session,
)
from tests.scores_row_lifecycle_test_helpers import _wait_until
from tests.submission_open_helpers import live_execution

GENERATION = 7
EPOCH = 0
CONTINUE = TierJobContinue()


pytestmark = pytest.mark.usefixtures("no_scores_row_runs")


def _stamp(scope: ComputeScope) -> TierLadderStamp | None:
    return tier_row_run_registry._ladder_stamp_by_scope_key.get(InferenceRowScope.from_root(scope))


def _ended() -> bool:
    return False


# --- The registry side: the stamped CANCEL and a claim for an ended execution ---


@pytest.fixture
def registry_run(sample_turn) -> tuple[RowRun, ComputeScope]:
    player_id = inference_target_player_id(sample_turn)
    run = new_tier_row_run(ladder_session(sample_turn, player_id))
    register_row_run(run, scope_index=ScopeIndexPolicy.TAKE)
    return run, ladder_scope(sample_turn, player_id)


def _claim(scope: ComputeScope, *, generation: int = GENERATION) -> RowRun | None:
    claim = claim_tier_ladder(
        scope, execution_generation=generation, scores_epoch=EPOCH, is_execution_live=live_execution
    )
    return None if claim is None else claim.run


def test_a_stamped_cancel_cancels_the_run_its_stamp_names(registry_run):
    run, scope = registry_run
    assert _claim(scope) is run

    cancelled = apply_scores_row_lifecycle(
        RowLifecycleOp.CANCEL, StampedLadderRun(scope=scope, execution_generation=GENERATION)
    )

    assert cancelled == run.run_id
    assert run.session.cancel_token.is_cancelled()
    assert get_row_run(run.run_id) is None
    assert get_persist_admission(run.run_id) is PersistAdmission.CANCEL_DENY
    assert _stamp(scope) is None


def test_a_stamped_cancel_leaves_a_stamp_of_a_newer_execution(registry_run):
    run, scope = registry_run
    assert _claim(scope) is run
    assert _claim(scope, generation=GENERATION + 1) is run

    cancelled = apply_scores_row_lifecycle(
        RowLifecycleOp.CANCEL, StampedLadderRun(scope=scope, execution_generation=GENERATION)
    )

    assert cancelled is None
    assert not run.session.cancel_token.is_cancelled()
    assert get_row_run(run.run_id) is run
    assert get_persist_admission(run.run_id) is PersistAdmission.ALLOW
    assert _stamp(scope) == TierLadderStamp(run.run_id, GENERATION + 1, EPOCH)


@pytest.mark.parametrize("generation", [GENERATION, GENERATION + 1], ids=["serving", "stale"])
@pytest.mark.parametrize("reopened", [False, True], ids=["no-reopen", "reopened"])
def test_a_claim_for_an_ended_execution_changes_nothing(
    sample_turn, registry_run, generation, reopened
):
    detached, scope = registry_run
    assert _claim(scope) is detached
    apply_scores_row_lifecycle(RowLifecycleOp.DETACH, detached.run_id)
    others = [detached]
    if reopened:
        others.append(new_tier_row_run(ladder_session(sample_turn, scope.player_id)))
        register_row_run(others[-1], scope_index=ScopeIndexPolicy.TAKE)
    stamp_before = _stamp(scope)

    with pytest.raises(ComputeExecutionEndedError):
        claim_tier_ladder(
            scope,
            execution_generation=generation,
            scores_epoch=EPOCH,
            is_execution_live=_ended,
        )

    assert _stamp(scope) == stamp_before
    assert [get_row_run(run.run_id) for run in others] == others


def test_a_stamped_target_takes_only_cancel(registry_run):
    _run, scope = registry_run
    stamped = StampedLadderRun(scope=scope, execution_generation=GENERATION)

    for op in (RowLifecycleOp.DETACH, RowLifecycleOp.RETIRE):
        with pytest.raises(TypeError):
            apply_scores_row_lifecycle(op, stamped)


# --- A scores execution aborted on the orchestrator ---


def _listen(ladder: ShellLadder) -> None:
    """Attach the scores scope-outcome listener to the ladder's orchestrator."""
    ladder.orchestrator.observers.register_scope_outcome_listener(
        ladder.scheduler._on_orchestrator_scope_outcome
    )


def _abort(ladder: ShellLadder) -> int:
    generation = ladder.orchestrator.nodes[ladder.scope].execution_generation
    assert ladder.orchestrator.abort_scope(
        ladder.scope,
        ComputeScopeAbortedError("game changed"),
        expected_execution_generation=generation,
    )
    return generation


def _aborted_snapshot(ladder: ShellLadder, generation: int) -> ScopeLifecycleSnapshot:
    return ScopeLifecycleSnapshot(
        scope=ladder.scope,
        state="failed",
        execution_generation=generation,
        result_wire=None,
        error=ComputeScopeAbortedError("game changed"),
    )


def _record_row_terminals(ladder: ShellLadder, monkeypatch) -> list[dict[str, object]]:
    delivered: list[dict[str, object]] = []
    monkeypatch.setattr(
        ladder.scheduler, "_deliver_row_terminal", lambda **kwargs: delivered.append(kwargs)
    )
    return delivered


@pytest.mark.parametrize("stream_closed", [False, True], ids=["stream-open", "stream-closed"])
def test_aborting_a_running_tier_step_cancels_its_stamped_run(ladder, monkeypatch, stream_closed):
    _listen(ladder)
    delivered = _record_row_terminals(ladder, monkeypatch)
    ladder.submit()
    ladder.run_tier(CONTINUE)
    stamped = ladder.session
    work = ladder.submitted_work[-1]
    job_wire = work.job_wire_for(ladder.scope)
    if stream_closed:
        ladder.close_stream()

    generation = _abort(ladder)

    assert stamped.cancel_token.is_cancelled()
    assert get_persist_admission(stamped.run_id) is PersistAdmission.CANCEL_DENY
    assert get_row_run(stamped.run_id) is None
    assert stamped.run_id not in ladder.scheduler._runs
    assert _stamp(ladder.scope) is None

    # The solve the abort stopped still returns; its result reaches nothing.
    with patch(
        "api.analytics.scores.compute_orchestration.run_inference_tier_job",
        return_value=durable_row_complete("after the abort"),
    ):
        result_wire = work.run_step(job_wire)
    ladder.orchestrator.complete_pool_step(ladder.scope, generation, result_wire=result_wire)

    assert ladder.persisted_summary() is None
    assert not decide_scores_row_persist(stamped.run_id).allowed
    assert delivered == []


def test_a_wire_build_for_an_aborted_execution_claims_nothing(ladder):
    _listen(ladder)
    ladder.submit()
    ladder.run_tier(CONTINUE)
    stamped_id = ladder.session.run_id
    picked_before_abort = ladder.submitted_work[-1]
    ladder.close_stream()
    _abort(ladder)
    reopened = ladder.open_stream()
    background = ladder.register_background_run()

    with pytest.raises(ComputeExecutionEndedError):
        picked_before_abort.job_wire_for(ladder.scope)

    assert _stamp(ladder.scope) is None
    assert get_row_run(stamped_id) is None
    assert get_row_run_phase(reopened.run_id) is RowRunPhase.REGISTERED
    assert get_row_run_phase(background.run_id) is RowRunPhase.REGISTERED
    assert {reopened.run_id, background.run_id} <= set(ladder.scheduler._runs)


# --- Explicit cancel_run reaches the same listener path ---


def _cancel_run(ladder: ShellLadder, run_id: str, monkeypatch) -> None:
    """Cancel ``run_id`` as an explicit cancel does, aborting the ladder's orchestrator."""
    monkeypatch.setattr("api.compute.runtime.get_compute_orchestrator", lambda: ladder.orchestrator)
    with ladder.scheduler._lock:
        ladder.scheduler._execution_generation_by_run_id[run_id] = ladder.orchestrator.nodes[
            ladder.scope
        ].execution_generation
    ladder.scheduler.cancel_run(run_id)
    assert ladder.orchestrator.nodes[ladder.scope].state == "failed"


def test_cancelling_the_stamped_run_leaves_the_listener_only_its_stamp(ladder, monkeypatch):
    _listen(ladder)
    ladder.submit()
    ladder.run_tier(CONTINUE)
    stamped = ladder.session
    ladder.submitted_work[-1].job_wire_for(ladder.scope)

    _cancel_run(ladder, stamped.run_id, monkeypatch)

    assert _stamp(ladder.scope) is None
    assert stamped.cancel_token.is_cancelled()
    assert get_persist_admission(stamped.run_id) is PersistAdmission.CANCEL_DENY

    # The step in flight when the cancel landed persists late.
    SCORES_PERSISTENCE_POLICY.persist(
        ladder.ctx,
        ladder.scope,
        {
            "runId": stamped.run_id,
            "rowComplete": durable_row_complete("late persist after cancel").row_complete,
            "onWalk": False,
        },
    )

    assert ladder.persisted_summary() is None


def test_cancelling_a_reopened_run_cancels_the_resumable_detached_shell(ladder, monkeypatch):
    _listen(ladder)
    ladder.submit()
    ladder.run_tier(CONTINUE)
    detached = ladder.session
    ladder.close_stream()
    reopened = ladder.open_stream()
    assert _stamp(ladder.scope).run_id == detached.run_id

    _cancel_run(ladder, reopened.run_id, monkeypatch)

    assert detached.cancel_token.is_cancelled()
    assert get_row_run(detached.run_id) is None
    assert get_persist_admission(detached.run_id) is PersistAdmission.CANCEL_DENY
    assert _stamp(ladder.scope) is None
    for run_id in (detached.run_id, reopened.run_id):
        assert not decide_scores_row_persist(run_id).allowed


# --- #632 D10, restated: an aborted execution never serves again ---


def test_an_aborted_execution_hands_no_ladder_over(ladder):
    ladder.submit()
    ladder.run_tier(CONTINUE)
    detached_id = ladder.session.run_id
    ladder.close_stream()
    aborted_generation = _abort(ladder)
    reopened = ladder.open_stream()
    fresh_ladder = get_row_run(reopened.run_id).ladder_state

    ladder.submit(force_fresh=True)
    wire = ladder.submitted_work[-1].job_wire_for(ladder.scope)

    assert wire["runId"] == reopened.run_id
    assert get_row_run(reopened.run_id).ladder_state is fresh_ladder
    assert fresh_ladder.next_step_index == 0
    assert get_row_run(detached_id) is None
    assert _stamp(ladder.scope).execution_generation != aborted_generation


def test_a_late_listener_leaves_a_run_restamped_for_the_next_execution(ladder):
    ladder.submit()
    ladder.run_tier(CONTINUE)
    stamped = ladder.session
    aborted_generation = _abort(ladder)
    ladder.submit(force_fresh=True)
    next_generation = ladder.orchestrator.nodes[ladder.scope].execution_generation
    wire = ladder.submitted_work[-1].job_wire_for(ladder.scope)
    assert wire["runId"] == stamped.run_id

    ladder.scheduler._on_orchestrator_scope_outcome(_aborted_snapshot(ladder, aborted_generation))

    assert not stamped.cancel_token.is_cancelled()
    assert get_row_run_phase(stamped.run_id) is RowRunPhase.REGISTERED
    assert _stamp(ladder.scope).execution_generation == next_generation


def test_reusing_a_registered_run_across_executions_waits_on_its_tier_lock(ladder, monkeypatch):
    """The next execution's step on the same run starts after the aborted one's step ends.

    It carries that run's own ladder progress, stamped at the same scores epoch.
    """
    aborted_step_started = threading.Event()
    release_aborted_step = threading.Event()
    tier_indexes: list[int] = []

    def tier_step(state: PolicyLadderState, *_args, **_kwargs) -> None:
        tier_indexes.append(state.next_step_index)
        if len(tier_indexes) == 1:
            aborted_step_started.set()
            release_aborted_step.wait(timeout=2.0)
        state.next_step_index += 1

    monkeypatch.setattr(
        "api.analytics.military_score_inference.inference_row_runner.run_policy_ladder_tier_step",
        tier_step,
    )
    ladder.submit()
    ladder.run_tier(CONTINUE)
    run_id = ladder.session.run_id
    aborted_work = ladder.submitted_work[-1]
    aborted_wire = aborted_work.job_wire_for(ladder.scope)
    aborted_stamp = _stamp(ladder.scope)
    aborted_step = threading.Thread(target=aborted_work.run_step, args=(aborted_wire,))
    aborted_step.start()
    _wait_until(aborted_step_started.is_set)

    _abort(ladder)
    ladder.submit(force_fresh=True)
    next_work = ladder.submitted_work[-1]
    next_wire = next_work.job_wire_for(ladder.scope)
    next_step = threading.Thread(target=next_work.run_step, args=(next_wire,))
    next_step.start()
    next_step.join(timeout=0.2)
    blocked_on_tier_lock = next_step.is_alive()
    release_aborted_step.set()
    aborted_step.join(timeout=2.0)
    next_step.join(timeout=2.0)

    assert blocked_on_tier_lock
    assert next_wire["runId"] == run_id
    assert _stamp(ladder.scope).scores_epoch == aborted_stamp.scores_epoch
    assert tier_indexes == [1, 2]

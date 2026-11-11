"""A scoreboard tier ladder carries on with its own RowRun after its stream closes.

The orchestrator tests run the real scores ``tier_solve`` wire builder and step
on a pool that never runs work, with the tier job scripted. A shell whose
stream closed mid-ladder resumes only for the same node execution and scores
epoch; anything else retires it and takes the admit path.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from api.analytics.fleet import REGISTRATION as FLEET_REGISTRATION
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_row_runner import TierJobOutcome
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.scores import REGISTRATION as SCORES_REGISTRATION
from api.analytics.scores.compute_orchestration import (
    SCORES_TIER_SOLVE,
    build_scores_tier_solve_job_wire,
)
from api.analytics.scores.row_lifecycle import apply_scores_row_lifecycle
from api.analytics.scores.tier_row_run_registry import (
    _detach_row_run,
    clear_row_runs,
    get_resumable_row_run_for_scope,
    get_row_run,
    register_row_run,
    release_tier_ladder_for_scope,
    reset_tier_row_run_registry_for_tests,
    stamp_tier_ladder,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute import ComputeOrchestrator, ComputeRequest, ComputeScope, build_compute_registry
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.compute.pools import ThreadStepWork
from api.compute.runtime import reset_orchestrators_for_tests
from api.compute.wire import DependencyOutputs
from api.streaming.table_stream.row_run_admission import RowLifecycleOp

from tests.export_chain_test_fixtures import export_chain_query_context
from tests.scores_exports_helpers import GAME_ID, inference_target_player_id, perspective
from tests.submission_open_helpers import explicit_submission_open

GENERATION = 7
EPOCH = 0


@pytest.fixture(autouse=True)
def _clean_registries() -> Iterator[None]:
    reset_tier_row_run_registry_for_tests()
    reset_inference_row_scheduler_for_tests()
    reset_orchestrators_for_tests()
    yield
    reset_tier_row_run_registry_for_tests()
    reset_inference_row_scheduler_for_tests()
    reset_orchestrators_for_tests()


def _session(sample_turn, player_id: int) -> InferenceRowStreamSession:
    score = next(row for row in sample_turn.scores if row.ownerid == player_id)
    return InferenceRowStreamSession(
        player_id=player_id,
        observation=build_inference_observation(score, sample_turn),
        turn=sample_turn,
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn_number=sample_turn.settings.turn,
    )


def _scope(sample_turn, player_id: int) -> ComputeScope:
    return ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=GAME_ID,
        perspective=perspective(sample_turn),
        turn=sample_turn.settings.turn,
        player_id=player_id,
    )


def _durable_row_complete(summary: str) -> TierJobOutcome:
    return TierJobOutcome(
        row_complete=row_complete_with_summary(
            InferenceResult(status=STATUS_EXACT, solutions=(), diagnostics={}),
            summary=summary,
        ),
    )


# --- The resume guard on the registry ---


@pytest.fixture
def registry_run(sample_turn) -> tuple[RowRun, ComputeScope]:
    player_id = inference_target_player_id(sample_turn)
    run = RowRun(_session(sample_turn, player_id))
    register_row_run(run, initialize_ladder=False)
    return run, _scope(sample_turn, player_id)


def _resumable(scope: ComputeScope, *, generation: int = GENERATION, epoch: int = EPOCH):
    return get_resumable_row_run_for_scope(
        scope, execution_generation=generation, scores_epoch=epoch
    )


def _stamp_and_detach(run: RowRun) -> None:
    stamp_tier_ladder(run, execution_generation=GENERATION, scores_epoch=EPOCH)
    _detach_row_run(run.run_id)


def test_a_detached_run_resumes_for_the_same_node_execution_and_epoch(registry_run):
    run, scope = registry_run
    _stamp_and_detach(run)

    assert _resumable(scope) is run
    assert _resumable(scope) is run


def test_a_run_detached_before_its_ladder_started_does_not_resume(registry_run):
    run, scope = registry_run
    _detach_row_run(run.run_id)

    assert _resumable(scope) is None
    assert get_row_run(run.run_id) is run


@pytest.mark.parametrize(
    ("generation", "epoch"),
    [(GENERATION + 1, EPOCH), (GENERATION, EPOCH + 1)],
    ids=["node-replaced", "epoch-changed"],
)
def test_a_mismatched_resume_retires_the_detached_shell(registry_run, generation, epoch):
    run, scope = registry_run
    _stamp_and_detach(run)

    assert _resumable(scope, generation=generation, epoch=epoch) is None
    assert get_row_run(run.run_id) is None
    assert _resumable(scope) is None


def test_a_registered_run_wins_over_the_detached_one(sample_turn, registry_run):
    detached, scope = registry_run
    _stamp_and_detach(detached)
    reopened = RowRun(_session(sample_turn, scope.player_id))
    register_row_run(reopened, initialize_ladder=False)

    assert _resumable(scope) is reopened

    stamp_tier_ladder(reopened, execution_generation=GENERATION, scores_epoch=EPOCH)
    assert get_row_run(detached.run_id) is None
    assert get_row_run(reopened.run_id) is reopened


def test_retire_after_write_clears_the_resume_entry(registry_run):
    run, scope = registry_run
    _stamp_and_detach(run)

    apply_scores_row_lifecycle(RowLifecycleOp.RETIRE, run.run_id)

    assert _resumable(scope) is None


def test_a_full_invalidate_clears_the_resume_entry(registry_run):
    run, scope = registry_run
    _stamp_and_detach(run)

    clear_row_runs()

    assert _resumable(scope) is None


def test_the_node_reaching_terminal_retires_only_its_own_entry(registry_run):
    run, scope = registry_run
    _stamp_and_detach(run)

    release_tier_ladder_for_scope(scope, execution_generation=GENERATION - 1)
    assert _resumable(scope) is run

    release_tier_ladder_for_scope(scope, execution_generation=GENERATION)
    assert _resumable(scope) is None
    assert get_row_run(run.run_id) is None


@pytest.mark.parametrize("state", ["complete", "failed"])
def test_the_scope_outcome_listener_retires_the_entry_on_terminal(registry_run, state):
    run, scope = registry_run
    _stamp_and_detach(run)

    InferenceRowScheduler()._on_orchestrator_scope_outcome(
        ScopeLifecycleSnapshot(
            scope=scope,
            state=state,
            execution_generation=GENERATION,
            result_wire=None,
            error=RuntimeError("hop failed") if state == "failed" else None,
        )
    )

    assert get_row_run(run.run_id) is None


# --- A ladder on the orchestrator whose stream closes mid-solve ---


class _ShellLadder:
    """The shell scoreboard ladder for one player, opened through a live scores stream."""

    def __init__(self, sample_turn, persistence) -> None:
        self.player_id = inference_target_player_id(sample_turn)
        self.persistence = persistence
        self.scheduler = InferenceRowScheduler(defer_orchestrator_submit=True)
        self.stream_scope = InferenceStreamScope(
            game_id=GAME_ID,
            perspective=perspective(sample_turn),
            turn_number=sample_turn.settings.turn,
        )
        self.stream_token = self.scheduler.begin_scope(self.stream_scope)
        self.session = _session(sample_turn, self.player_id)
        self.scheduler.enqueue_tier_ladder(self.session, stream_token=self.stream_token)
        self.ctx = export_chain_query_context(
            sample_turn,
            persistence=persistence,
            scheduler=self.scheduler,
            seed_fleet_prerequisites_for=self.player_id,
        )
        self.scope = _scope(sample_turn, self.player_id)
        self.submitted_work: list[ThreadStepWork] = []
        self.orchestrator = ComputeOrchestrator(
            compute_registry=build_compute_registry((FLEET_REGISTRATION, SCORES_REGISTRATION)),
            pool_submitter=lambda _node, _step, *, work: self.submitted_work.append(work),
        )
        self.tier_runs: list[str] = []

    def submit(self) -> None:
        self.orchestrator.submit(
            ComputeRequest(ctx=self.ctx, scope=self.scope, step_kind=SCORES_TIER_SOLVE)
        )
        assert self.orchestrator.nodes[self.scope].state == "running"

    def close_stream(self) -> None:
        self.scheduler.detach_inference_stream(
            self.stream_scope, (self.session,), stream_token=self.stream_token
        )

    def run_tier(self, outcome: TierJobOutcome | BaseException) -> None:
        """Build and run the node's last submitted tier step, then hand the result back."""

        def tier_job(run: RowRun, _callbacks) -> TierJobOutcome:
            self.tier_runs.append(run.run_id)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with patch(
            "api.analytics.scores.compute_orchestration.run_inference_tier_job",
            side_effect=tier_job,
        ):
            try:
                result_wire = self.orchestrator.execute_pool_step(
                    self.scope, self.submitted_work[-1]
                )
            except Exception as exc:
                self.orchestrator.complete_pool_step(self.scope, error=exc)
                return
        self.orchestrator.complete_pool_step(self.scope, result_wire=result_wire)

    def persisted_summary(self) -> str | None:
        row = self.persistence.get_row(
            GAME_ID, self.scope.perspective, self.scope.turn, self.player_id
        )
        return None if row is None else row.summary


@pytest.fixture
def ladder(sample_turn, persistence) -> _ShellLadder:
    return _ShellLadder(sample_turn, persistence)


def test_closing_the_stream_mid_ladder_resumes_the_same_run_to_a_durable_persist(ladder):
    ladder.submit()
    stream_run_id = ladder.session.run_id
    ladder.run_tier(TierJobOutcome(enqueue_continuation=True))

    ladder.close_stream()
    with patch("api.analytics.scores.exports.admit_scores_export_work") as admit:
        ladder.run_tier(TierJobOutcome(enqueue_continuation=True))
        ladder.run_tier(_durable_row_complete("resumed after close"))
        admit.assert_not_called()

    node = ladder.orchestrator.nodes[ladder.scope]
    assert node.state == "complete", node.error
    assert ladder.tier_runs == [stream_run_id] * 3
    assert ladder.persisted_summary() == "resumed after close"
    # ALLOW + DETACHED persists, then retires the shell after the write.
    assert get_row_run(stream_run_id) is None


@pytest.mark.parametrize("stream_closed", [False, True], ids=["streams-open", "streams-closed"])
def test_a_failing_tier_fails_the_same_way_with_the_stream_open_or_closed(ladder, stream_closed):
    ladder.submit()
    ladder.run_tier(TierJobOutcome(enqueue_continuation=True))
    if stream_closed:
        ladder.close_stream()

    ladder.run_tier(RuntimeError("forced tier failure"))

    node = ladder.orchestrator.nodes[ladder.scope]
    assert node.state == "failed"
    assert type(node.error) is RuntimeError
    assert str(node.error) == "forced tier failure"
    assert ladder.tier_runs == [ladder.session.run_id] * 2


def test_a_fleet_epoch_change_while_detached_takes_the_admit_path(ladder):
    ladder.submit()
    stream_run_id = ladder.session.run_id
    ladder.run_tier(TierJobOutcome(enqueue_continuation=True))
    ladder.close_stream()

    ladder.ctx.export_services["fleet"].persistence.invalidate_player_ledgers_from_turn(
        GAME_ID, ladder.scope.perspective, ladder.scope.turn - 1, ladder.player_id
    )
    wire = build_scores_tier_solve_job_wire(
        ladder.scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ladder.ctx,
        submission_open=explicit_submission_open(),
        execution_generation=ladder.orchestrator.nodes[ladder.scope].execution_generation,
    )

    assert get_row_run(stream_run_id) is None
    assert wire["runId"] != stream_run_id


def test_a_replaced_node_does_not_resume_the_old_run(ladder):
    ladder.submit()
    stream_run_id = ladder.session.run_id
    ladder.run_tier(TierJobOutcome(enqueue_continuation=True))
    ladder.close_stream()
    old_generation = ladder.orchestrator.nodes[ladder.scope].execution_generation

    wire = build_scores_tier_solve_job_wire(
        ladder.scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ladder.ctx,
        submission_open=explicit_submission_open(),
        execution_generation=old_generation + 1,
    )

    assert get_row_run(stream_run_id) is None
    assert wire["runId"] != stream_run_id


def test_reopening_the_stream_mid_ladder_starts_a_fresh_run_that_wins(ladder, sample_turn):
    ladder.submit()
    first_run_id = ladder.session.run_id
    ladder.run_tier(TierJobOutcome(enqueue_continuation=True))
    ladder.close_stream()

    reopened_token = ladder.scheduler.begin_scope(ladder.stream_scope)
    reopened = _session(sample_turn, ladder.player_id)
    ladder.scheduler.enqueue_tier_ladder(reopened, stream_token=reopened_token)
    ladder.run_tier(_durable_row_complete("fresh run after reopen"))

    assert ladder.tier_runs == [first_run_id, reopened.run_id]
    assert get_row_run(first_run_id) is None
    assert ladder.persisted_summary() == "fresh run after reopen"

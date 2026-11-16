"""An inline step's finish applies only to the execution that is still running it.

An inline step runs outside the orchestrator lock. When its execution ends
while the step runs (an abort, or a stop's settle), the step's return or
raise is ignored and recorded as ``inline_finish_ignored``, as a pool step's
late finish is recorded as ``pool_finish_ignored``. So an ended node is
never re-queued by an epoch retry or a continue into its next step.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pytest
from api.analytics.exports.empty import empty_export_catalog_for
from api.analytics.registration import TurnAnalyticRegistration
from api.analytics.scores.compute_orchestration import (
    SCORES_MATERIALIZE,
    ScoresPersistencePolicy,
)
from api.compute import (
    AnalyticComputeProfile,
    ComputeOrchestrator,
    ComputeRequest,
    ComputeStepSpec,
    build_compute_registry,
)
from api.compute.errors import ComputeScopeAbortedError
from api.compute.in_flight_settle import GameWork, RunningDisposition
from api.compute.orchestrator_observers import StepItemIgnoredReason
from api.compute.submission_open import SubmissionOpen
from api.compute.wire import StepResult
from api.services.backfill_walk_stop import stop_backfill_walks

from tests.compute_orchestrator_fixtures import (
    ROW_SCOPE_KEY,
    RecordingPersistencePolicy,
    make_compute_scope,
    make_export_scope,
)
from tests.fixtures.export_framework.diamond_exports import SHARED_ID
from tests.fixtures.export_framework.harness import (
    DIAMOND_FIXTURE_EXPORT_REGISTRY,
    make_fixture_query_context,
)
from tests.test_compute_foundation import _catalog_entry
from tests.test_orchestrator_settle import _StopEverything

_ABORT = ComputeScopeAbortedError("ended while its inline step ran")

IgnoredFinish = tuple[str, str, bool]


class _InlineHarness:
    """One node whose inline first step runs ``run(job)``.

    A second ``next_step_kind`` step, when given, runs on a pool whose
    submissions are recorded and never executed.
    """

    def __init__(
        self,
        sample_turn,
        run: Callable[[Mapping[str, object]], object],
        *,
        next_step_kind: str | None = None,
    ) -> None:
        self.ctx = make_fixture_query_context(sample_turn, registry=DIAMOND_FIXTURE_EXPORT_REGISTRY)
        self.scope = make_compute_scope(SHARED_ID, make_export_scope(sample_turn))
        self.persistence = RecordingPersistencePolicy()
        self.runs = 0
        self.pool_submissions: list[str] = []

        def counted_run(job):
            self.runs += 1
            return run(job)

        steps = [ComputeStepSpec(step_kind="materialize", backend="inline")]
        build_wires = [("materialize", lambda scope, **_kwargs: {"scope": scope.analytic_id})]
        run_steps = [("materialize", counted_run)]
        if next_step_kind is not None:
            steps.append(ComputeStepSpec(step_kind=next_step_kind, backend="thread"))
            build_wires.append((next_step_kind, lambda _scope, **_kwargs: {}))
            run_steps.append((next_step_kind, lambda _job: StepResult(outcome="complete")))
        self.orchestrator = ComputeOrchestrator(
            compute_registry=build_compute_registry(
                (
                    TurnAnalyticRegistration(
                        catalog_entry=_catalog_entry(SHARED_ID),
                        compute=lambda _ctx: {"analyticId": SHARED_ID},
                        export_catalog=empty_export_catalog_for(SHARED_ID),
                        scope_key_spec=ROW_SCOPE_KEY,
                        compute_profile=AnalyticComputeProfile(steps=tuple(steps)),
                        persistence_policy=self.persistence,
                        build_step_job_wires=tuple(build_wires),
                        run_steps=tuple(run_steps),
                    ),
                )
            ),
            pool_submitter=lambda _node, step, **_kwargs: self.pool_submissions.append(
                step.step_kind
            ),
        )
        self.ignored = self._record_ignored_finishes()

    def _record_ignored_finishes(self) -> list[IgnoredFinish]:
        """``(kind, reason, hadError)`` of each ``inline_finish_ignored`` record."""
        ignored: list[IgnoredFinish] = []

        def record(kind, _scope, _node, _generation, _step_kind, _step_index, detail) -> None:
            if kind == "inline_finish_ignored":
                ignored.append((kind, detail["reason"], detail["hadError"]))

        self.orchestrator.observers.register_lifecycle_listener(record)
        return ignored

    def abort_and_bump_epoch(self) -> None:
        """What a bump's settle does to this execution while its step runs."""
        self.orchestrator.abort_scope(self.scope, _ABORT)
        self.persistence.invalidate(self.ctx, self.scope)

    def submit(self):
        return self.orchestrator.submit(ComputeRequest(ctx=self.ctx, scope=self.scope))

    def assert_ended_once(self, *, error: BaseException | None = None) -> None:
        node = self.orchestrator.nodes[self.scope]
        assert node.state == "failed"
        if error is None:
            assert isinstance(node.error, ComputeScopeAbortedError)
        else:
            assert node.error is error
        assert self.runs == 1
        assert self.orchestrator.metrics.epoch_discards == 0
        assert self.persistence.persist_calls == []
        assert self.pool_submissions == []


def test_an_aborted_inline_step_that_returns_after_an_epoch_bump_is_not_requeued(sample_turn):
    harness: _InlineHarness

    def run(job):
        harness.abort_and_bump_epoch()
        return {"result": job["scope"]}

    harness = _InlineHarness(sample_turn, run)

    handle = harness.submit()

    harness.assert_ended_once(error=_ABORT)
    assert handle.error is _ABORT
    assert harness.ignored == [
        ("inline_finish_ignored", StepItemIgnoredReason.NODE_NOT_RUNNING, False)
    ]


def test_an_aborted_inline_step_that_raises_keeps_the_abort_as_its_error(sample_turn):
    harness: _InlineHarness

    def run(_job):
        harness.abort_and_bump_epoch()
        raise RuntimeError("the step failed after its execution ended")

    harness = _InlineHarness(sample_turn, run)

    harness.submit()

    harness.assert_ended_once(error=_ABORT)
    assert harness.ignored == [
        ("inline_finish_ignored", StepItemIgnoredReason.NODE_NOT_RUNNING, True)
    ]


def test_aborting_a_running_inline_step_records_its_completion_on_the_inline_surface(
    sample_turn,
):
    harness: _InlineHarness
    completions: list[tuple[str, str, str]] = []

    def run(_job):
        harness.orchestrator.abort_scope(harness.scope, _ABORT)
        return {"result": "ignored"}

    harness = _InlineHarness(sample_turn, run)
    harness.orchestrator.observers.register_step_complete_listener(
        lambda _scope, _node, step_kind, _index, surface, terminal_state: completions.append(
            (step_kind, surface, terminal_state)
        )
    )

    harness.submit()

    harness.assert_ended_once(error=_ABORT)
    assert completions == [("materialize", "inline", "failed")]


def test_an_inline_step_a_settle_aborts_while_it_runs_does_not_continue_into_its_next_step(
    sample_turn,
):
    harness: _InlineHarness

    def materialize_while_a_settle_aborts_it(_job):
        harness.orchestrator.settle_in_flight_work(
            GameWork(game_id=harness.scope.game_id, analytic_ids=frozenset({SHARED_ID})),
            _StopEverything(running_disposition=RunningDisposition.ABORT),
        )
        return StepResult(outcome="continue")

    harness = _InlineHarness(
        sample_turn, materialize_while_a_settle_aborts_it, next_step_kind="tier_solve"
    )

    harness.submit()

    harness.assert_ended_once()
    assert harness.ignored == [
        ("inline_finish_ignored", StepItemIgnoredReason.NODE_NOT_RUNNING, False)
    ]


@pytest.mark.usefixtures("no_scores_row_runs")
def test_a_scoreboard_materialize_the_game_stop_aborts_while_it_runs_is_not_resumed(
    ladder, monkeypatch
):
    """The real scores materialize step runs while a game stop aborts its walk node.

    Its return is ignored: the node stays aborted and never continues into
    its tier solve. The sample turn's scoreboard evidence is already closed,
    so the submit names its entry step and satisfaction is turned off, for
    the step to run at all.
    """
    monkeypatch.setattr(ScoresPersistencePolicy, "is_satisfied", lambda *_args: False)
    started: list[str] = []
    ignored: list[IgnoredFinish] = []

    def stop_the_game_while_materialize_runs(scope, _node, step_kind) -> None:
        if scope == ladder.scope and step_kind == SCORES_MATERIALIZE:
            started.append(step_kind)
            stop_backfill_walks(ladder.orchestrator, ladder.ctx.game_id)()

    def record(kind, _scope, _node, _generation, _step_kind, _step_index, detail) -> None:
        if kind == "inline_finish_ignored":
            ignored.append((kind, detail["reason"], detail["hadError"]))

    ladder.orchestrator.observers.register_inline_start_listener(
        stop_the_game_while_materialize_runs
    )
    ladder.orchestrator.observers.register_lifecycle_listener(record)

    ladder.orchestrator.submit(
        ComputeRequest(
            ctx=ladder.ctx,
            scope=ladder.scope,
            step_kind=SCORES_MATERIALIZE,
            submission_open=SubmissionOpen(
                open_turn=ladder.scope.turn + 1, backfill_earlier_turns=True, on_walk=True
            ),
        )
    )

    assert started == [SCORES_MATERIALIZE]
    node = ladder.orchestrator.nodes[ladder.scope]
    assert node.state == "failed"
    assert isinstance(node.error, ComputeScopeAbortedError)
    assert ladder.submitted_work == []
    assert ignored == [("inline_finish_ignored", StepItemIgnoredReason.NODE_NOT_RUNNING, False)]
    assert ladder.persisted_summary() is None

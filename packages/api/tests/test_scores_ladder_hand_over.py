"""A RowRun that takes over a scope mid-ladder continues the ladder it takes over.

When a ``tier_solve`` wire build stamps a RowRun for a scope whose ladder another
run holds, the unfinished ladder moves to the stamped run (the winner) and every
other run for the scope is retired. The orchestrator tests run the real scores
``tier_solve`` wire builder and step on a pool that never runs work, with the
tier job scripted: a continuing tier finishes one tier of its run's ladder.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from unittest.mock import patch

import pytest
from api.analytics.export_types import ExportScope
from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.inference_row_runner import TierJobOutcome
from api.analytics.military_score_inference.inference_scheduler import (
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_domain_events import (
    HeldSolutionsUpdated,
    RowComplete,
)
from api.analytics.military_score_inference.inference_stream_rows import ScheduledInferenceRow
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.inference_stream_teardown import (
    HeldTierSubmission,
    InferenceStreamOrchestratorBinding,
)
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.military_score_inference.models import (
    InferenceResult,
    InferenceSolution,
    InferenceSolutionAction,
)
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    PriorTurnFleetTorpResolution,
)
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.scores import exports, tier_row_run_registry
from api.analytics.scores.compute_orchestration import (
    SCORES_PERSISTENCE_POLICY,
    build_scores_tier_solve_job_wire,
)
from api.analytics.scores.persist_decision import PersistDecision
from api.analytics.scores.tier_row_run_registry import (
    decide_scores_row_persist,
    get_row_run,
    reset_tier_row_run_registry_for_tests,
)
from api.compute.orchestrator_observers import ScopeLifecycleSnapshot
from api.compute.runtime import reset_orchestrators_for_tests
from api.compute.wire import DependencyOutputs
from api.services.inference_invalidation_service import InferenceInvalidationService

from tests.on_walk_helpers import fleet_persistence
from tests.scores_exports_helpers import GAME_ID
from tests.scores_ladder_helpers import ShellLadder, durable_row_complete
from tests.submission_open_helpers import explicit_submission_open

CONTINUE = TierJobOutcome(enqueue_continuation=True)
ABSENT = PersistDecision.refuse(should_retire=False)
HELD_SOLUTION = InferenceSolution(
    objective_value=20,
    actions=(InferenceSolutionAction(action_id="action_a", label="Action A", count=1),),
)


@pytest.fixture(autouse=True)
def _clean_registries() -> Iterator[None]:
    reset_tier_row_run_registry_for_tests()
    reset_inference_row_scheduler_for_tests()
    reset_orchestrators_for_tests()
    reset_inference_table_stream_registry_for_tests()
    yield
    reset_tier_row_run_registry_for_tests()
    reset_inference_row_scheduler_for_tests()
    reset_orchestrators_for_tests()
    reset_inference_table_stream_registry_for_tests()


@pytest.fixture
def ladder(sample_turn, persistence) -> ShellLadder:
    return ShellLadder(sample_turn, persistence)


def _assert_the_winner_alone_holds_the_scope(
    ladder: ShellLadder, winner_id: str, retired_ids: tuple[str, ...]
) -> None:
    assert decide_scores_row_persist(winner_id) == PersistDecision.allow(retire_after_write=False)
    winner = ladder.scheduler.row_run_for_player(ladder.stream_scope, ladder.player_id)
    assert winner is not None
    assert winner.run_id == winner_id
    for retired_id in retired_ids:
        assert decide_scores_row_persist(retired_id) == ABSENT
        assert retired_id not in ladder.scheduler._runs
        assert retired_id not in ladder.scheduler._execution_generation_by_run_id


def _queued_events(session: InferenceRowStreamSession) -> list[object]:
    events: list[object] = []
    while True:
        try:
            events.append(session.event_queue.get_nowait())
        except queue.Empty:
            return events


# --- T7: the winner continues the ladder it takes over ---


def _reopen_after_the_old_streams_finally(ladder: ShellLadder) -> tuple[str, ...]:
    ladder.close_stream()
    ladder.open_stream()
    return ()


def _reopen_before_the_old_streams_finally(ladder: ShellLadder) -> tuple[str, ...]:
    ladder.open_stream()
    return ()


def _reopen_after_a_claim_before_attach_admit(ladder: ShellLadder) -> tuple[str, ...]:
    """The reopened stream claims the scope, an admit registers first, then the stream's row."""
    ladder.close_stream()
    ladder.stream_token = ladder.scheduler.begin_scope(ladder.stream_scope)
    admitted = ladder.register_background_run()
    ladder.open_stream()
    return (admitted.run_id,)


TAKEOVERS = {
    "reopen-after-finally": _reopen_after_the_old_streams_finally,
    "reopen-before-finally": _reopen_before_the_old_streams_finally,
    "admit-duplicate-with-no-stamp": _reopen_after_a_claim_before_attach_admit,
}


@pytest.mark.parametrize("take_over", TAKEOVERS.values(), ids=TAKEOVERS.keys())
def test_a_stream_reopened_mid_ladder_continues_the_ladder_under_its_own_run(ladder, take_over):
    ladder.submit()
    stamped_id = ladder.session.run_id
    ladder.run_tier(CONTINUE)
    ladder.run_tier(CONTINUE)
    stamped_ladder = get_row_run(stamped_id).ladder_state

    duplicate_ids = take_over(ladder)
    winner_id = ladder.session.run_id
    ladder.run_tier(CONTINUE)

    assert ladder.tier_steps == [(stamped_id, 0), (stamped_id, 1), (winner_id, 2)]
    assert get_row_run(winner_id).ladder_state is stamped_ladder
    _assert_the_winner_alone_holds_the_scope(ladder, winner_id, (stamped_id, *duplicate_ids))

    ladder.run_tier(durable_row_complete("continued by the reopened stream"))
    assert ladder.orchestrator.nodes[ladder.scope].state == "complete"
    assert ladder.tier_runs[-1] == winner_id
    assert ladder.persisted_summary() == "continued by the reopened stream"


def test_a_stream_opened_at_a_walk_hop_continues_the_walks_ladder(ladder):
    shell_run_id = ladder.session.run_id
    ladder.close_stream()
    walk_run_id = ladder.register_background_run().run_id
    ladder.submit()
    ladder.run_tier(CONTINUE)
    assert ladder.tier_steps == [(walk_run_id, 0)]
    _assert_the_winner_alone_holds_the_scope(ladder, walk_run_id, (shell_run_id,))

    winner_id = ladder.open_stream().run_id
    ladder.run_tier(CONTINUE)

    assert ladder.tier_steps == [(walk_run_id, 0), (winner_id, 1)]
    _assert_the_winner_alone_holds_the_scope(ladder, winner_id, (walk_run_id,))


def test_a_reopen_during_the_last_tier_gets_the_terminal_through_orphan_delivery(ladder):
    ladder.submit()
    stamped_id = ladder.session.run_id
    ladder.run_tier(CONTINUE)
    result_wire = ladder.execute_tier(durable_row_complete("finished before the reopen saw it"))

    ladder.close_stream()
    reopened = ladder.open_stream()
    controller = InferenceTableStreamController(
        scope=ladder.stream_scope,
        stream_token=ladder.stream_token,
        turn=ladder.sample_turn,
        player_ids=(ladder.player_id,),
        scheduler=ladder.scheduler,
        game_id=GAME_ID,
        perspective=ladder.stream_scope.perspective,
    )
    controller.register_scheduled_row(
        ladder.player_id, ScheduledInferenceRow(player_id=ladder.player_id, session=reopened)
    )
    controller.attach()
    ladder.complete_tier(result_wire)

    node = ladder.orchestrator.nodes[ladder.scope]
    assert node.state == "complete"
    assert ladder.tier_runs == [stamped_id, stamped_id]
    assert ladder.persisted_summary() == "finished before the reopen saw it"
    assert get_row_run(stamped_id) is None

    ladder.scheduler._on_orchestrator_scope_outcome(
        ScopeLifecycleSnapshot(
            scope=ladder.scope,
            state="complete",
            execution_generation=node.execution_generation,
            result_wire=node.result_wire,
            error=None,
        )
    )

    terminals = [event for event in _queued_events(reopened) if isinstance(event, RowComplete)]
    assert [terminal.wire_payload.summary for terminal in terminals] == [
        "finished before the reopen saw it"
    ]
    assert reopened.run_id not in ladder.scheduler._runs


def test_a_reopen_after_a_soft_defer_starts_a_fresh_ladder(ladder):
    ladder.submit()
    stamped_id = ladder.session.run_id
    ladder.run_tier(CONTINUE)
    pending = TierJobOutcome(
        row_complete=row_complete_with_summary(
            InferenceResult(status="pending", solutions=(), diagnostics={}),
            summary="soft deferred",
        )
    )
    ladder.run_tier(pending)
    node = ladder.orchestrator.nodes[ladder.scope]
    assert node.state == "waiting_deps"
    generation = node.execution_generation
    assert get_row_run(stamped_id).ladder_state.ladder_complete

    ladder.close_stream()
    winner_id = ladder.open_stream().run_id
    fresh_ladder = get_row_run(winner_id).ladder_state
    ladder.submit(force_fresh=True)
    assert ladder.orchestrator.nodes[ladder.scope].execution_generation == generation
    ladder.run_tier(CONTINUE)

    assert ladder.tier_steps == [(stamped_id, 0), (stamped_id, 1), (winner_id, 0)]
    assert get_row_run(winner_id).ladder_state is fresh_ladder
    _assert_the_winner_alone_holds_the_scope(ladder, winner_id, (stamped_id,))


@pytest.mark.parametrize("stale", ["node-replaced", "epoch-changed"])
def test_a_reopen_against_a_stale_stamp_starts_a_fresh_ladder(ladder, stale):
    ladder.submit()
    stamped_id = ladder.session.run_id
    ladder.run_tier(CONTINUE)
    ladder.close_stream()
    winner_id = ladder.open_stream().run_id
    fresh_ladder = get_row_run(winner_id).ladder_state
    generation = ladder.orchestrator.nodes[ladder.scope].execution_generation
    if stale == "node-replaced":
        generation += 1
    else:
        fleet_persistence(ladder.ctx).invalidate_player_ledgers_from_turn(
            GAME_ID, ladder.scope.perspective, ladder.scope.turn - 1, ladder.player_id
        )

    wire = build_scores_tier_solve_job_wire(
        ladder.scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ladder.ctx,
        submission_open=explicit_submission_open(),
        execution_generation=generation,
    )

    assert wire["runId"] == winner_id
    assert get_row_run(winner_id).ladder_state is fresh_ladder
    assert fresh_ladder.next_step_index == 0
    _assert_the_winner_alone_holds_the_scope(ladder, winner_id, (stamped_id,))


# --- Choosing the scope's run and stamping it are one registry operation ---


class _RegistryLockWithReleaseHook:
    """The registry lock, running a one-shot action right after its next release.

    The action runs with the lock free, as another thread would between two
    registry calls of a wire build.
    """

    def __init__(self, lock: threading.Lock) -> None:
        self._lock = lock
        self._after_next_release: Callable[[], object] | None = None

    def run_after_next_release(self, action: Callable[[], object]) -> None:
        self._after_next_release = action

    def __enter__(self) -> None:
        self._lock.acquire()

    def __exit__(self, *_exc_info: object) -> None:
        self._lock.release()
        action, self._after_next_release = self._after_next_release, None
        if action is not None:
            action()


def _resume_the_closed_streams_run(
    ladder: ShellLadder, open_stream_soon: Callable[[], None]
) -> str:
    """The wire build resumes the closed stream's stamped ``DETACHED`` run."""
    ladder.submit()
    ladder.run_tier(CONTINUE)
    resumed_id = ladder.session.run_id
    ladder.close_stream()
    open_stream_soon()
    ladder.run_tier(CONTINUE)
    return resumed_id


def _claim_an_admitted_background_run(
    ladder: ShellLadder, open_stream_soon: Callable[[], None]
) -> str:
    """The wire build finds no run, admits a background run and takes it."""
    ladder.close_stream()
    admitted_ids: list[str] = []

    def admit_a_background_run(*_args: object, **_kwargs: object) -> bool:
        admitted_ids.append(ladder.register_background_run().run_id)
        open_stream_soon()
        return True

    with patch(
        "api.analytics.scores.exports.admit_scores_export_work",
        side_effect=admit_a_background_run,
    ):
        ladder.submit()
        ladder.run_tier(CONTINUE)
    return admitted_ids[0]


WIRE_BUILD_CHOICES = {
    "resume": _resume_the_closed_streams_run,
    "admit": _claim_an_admitted_background_run,
}


@pytest.mark.parametrize("choose_a_run", WIRE_BUILD_CHOICES.values(), ids=WIRE_BUILD_CHOICES.keys())
def test_a_stream_registered_while_the_wire_build_chooses_its_run_takes_the_ladder_next(
    ladder, monkeypatch, choose_a_run
):
    registry_lock = _RegistryLockWithReleaseHook(tier_row_run_registry._lock)
    monkeypatch.setattr(tier_row_run_registry, "_lock", registry_lock)

    def open_stream_at_the_next_registry_release() -> None:
        registry_lock.run_after_next_release(ladder.open_stream)

    chosen_id = choose_a_run(ladder, open_stream_at_the_next_registry_release)
    stream_id = ladder.session.run_id

    assert ladder.tier_runs[-1] == chosen_id
    assert decide_scores_row_persist(stream_id) == PersistDecision.allow(retire_after_write=False)
    chosen_ladder = get_row_run(chosen_id).ladder_state
    tiers_run = len(ladder.tier_steps)

    ladder.run_tier(CONTINUE)

    assert ladder.tier_steps[-1] == (stream_id, tiers_run)
    assert get_row_run(stream_id).ladder_state is chosen_ladder
    _assert_the_winner_alone_holds_the_scope(ladder, stream_id, (chosen_id,))


# --- A background run registered after a stream's run never takes its scope ---


def _admit_while_a_stream_registers_during_fleet_io(ladder: ShellLadder) -> None:
    """An export admit finds no run, then a stream registers while it resolves prior fleet."""
    resolve_prior_fleet = exports.resolve_prior_fleet_for_scores

    def open_stream_then_resolve(*args: object, **kwargs: object) -> object:
        ladder.open_stream()
        return resolve_prior_fleet(*args, **kwargs)

    export_scope = ExportScope(
        game_id=ladder.scope.game_id,
        perspective=ladder.scope.perspective,
        turn=ladder.scope.turn,
        player_id=ladder.player_id,
    )
    with patch.object(exports, "resolve_prior_fleet_for_scores", open_stream_then_resolve):
        assert exports.admit_scores_export_work(
            ladder.ctx,
            export_scope,
            backfill_earlier_turns=ladder.ctx.backfill_earlier_turns_enabled(),
        )


def _lose_a_connect_admission_to_a_successor_at_the_same_scope(ladder: ShellLadder) -> None:
    """A stream's connect admission is in flight across a T -> T' -> T toggle.

    The successor stream at T registers the player while the predecessor
    resolves prior fleet, so the predecessor's admission registers after it
    under a token that no longer owns the scope.
    """
    predecessor_token = ladder.scheduler.begin_scope(ladder.stream_scope)

    def toggle_back_then_resolve(_player_id: int) -> PriorTurnFleetTorpResolution:
        ladder.scheduler.begin_scope(
            replace(ladder.stream_scope, turn_number=ladder.stream_scope.turn_number - 1)
        )
        ladder.open_stream()
        return PriorTurnFleetTorpResolution(overlay=None, input_status="unavailable")

    predecessor = InferenceTableStreamController(
        scope=ladder.stream_scope,
        stream_token=predecessor_token,
        turn=ladder.sample_turn,
        player_ids=(ladder.player_id,),
        scheduler=ladder.scheduler,
        game_id=GAME_ID,
        perspective=ladder.stream_scope.perspective,
        resolve_fleet_torp_resolution_for_player=toggle_back_then_resolve,
        query_context=ladder.ctx,
    )
    predecessor.schedule_player_row(ladder.player_id)


LATE_BACKGROUND_REGISTRATIONS = {
    "admit-across-fleet-io": _admit_while_a_stream_registers_during_fleet_io,
    "lost-connect-admission": _lose_a_connect_admission_to_a_successor_at_the_same_scope,
}


@pytest.mark.parametrize(
    "register_late",
    LATE_BACKGROUND_REGISTRATIONS.values(),
    ids=LATE_BACKGROUND_REGISTRATIONS.keys(),
)
def test_a_background_run_registered_after_a_streams_run_loses_the_next_claim(
    ladder, register_late
):
    closed_id = ladder.session.run_id
    ladder.close_stream()
    runs_before = set(ladder.scheduler._runs)

    register_late(ladder)
    stream_id = ladder.session.run_id
    (background_id,) = set(ladder.scheduler._runs) - runs_before - {stream_id}
    ladder.submit()
    ladder.run_tier(CONTINUE)

    assert ladder.tier_runs == [stream_id]
    _assert_the_winner_alone_holds_the_scope(ladder, stream_id, (closed_id, background_id))


# --- The held top-K reaches the winner's stream without announcing evidence ---


def _hand_over_a_ladder_holding_solutions(ladder: ShellLadder) -> InferenceRowStreamSession:
    ladder.submit()
    stamped = get_row_run(ladder.session.run_id)
    ladder.run_tier(CONTINUE)
    stamped.ladder_state.catalog = ActionCatalog((), (), {})
    stamped.ladder_state.merged_solutions = [HELD_SOLUTION]

    ladder.close_stream()
    winner = ladder.open_stream()
    ladder.run_tier(CONTINUE)
    return winner


def test_the_winners_stream_gets_the_moved_ladders_held_solutions_once(sample_turn, persistence):
    evidence_updates: list[str] = []
    ladder = ShellLadder(
        sample_turn,
        persistence,
        on_held_solutions_updated=lambda session: evidence_updates.append(session.run_id),
    )

    winner = _hand_over_a_ladder_holding_solutions(ladder)

    held = [event for event in _queued_events(winner) if isinstance(event, HeldSolutionsUpdated)]
    assert len(held) == 1
    assert held[0].solutions == (HELD_SOLUTION,)
    assert held[0].observation == winner.observation
    assert evidence_updates == []


def test_a_hand_over_moves_no_fleet_or_scores_epoch(sample_turn, persistence):
    """T9: hand-over announces no inference evidence, so no fleet or scores epoch moves."""
    invalidations: list[InferenceInvalidationService] = []
    ladder = ShellLadder(
        sample_turn,
        persistence,
        on_held_solutions_updated=lambda session: invalidations[0].on_inference_evidence_updated(
            session.game_id, session.perspective, session.turn_number, session.player_id
        ),
    )
    fleet = fleet_persistence(ladder.ctx)
    invalidations.append(InferenceInvalidationService(persistence, fleet_persistence=fleet))
    later_turns = (ladder.scope.turn, ladder.scope.turn + 1, ladder.scope.turn + 2)

    def epochs() -> tuple[int, ...]:
        return (
            fleet.player_invalidation_generation(
                GAME_ID, ladder.scope.perspective, ladder.player_id
            ),
            *(
                SCORES_PERSISTENCE_POLICY.invalidation_generation(
                    ladder.ctx, replace(ladder.scope, turn=turn)
                )
                for turn in later_turns
            ),
        )

    before = epochs()
    with patch.object(
        fleet,
        "invalidate_player_ledgers_from_turn",
        wraps=fleet.invalidate_player_ledgers_from_turn,
    ) as invalidate_ledgers:
        _hand_over_a_ladder_holding_solutions(ladder)

    invalidate_ledgers.assert_not_called()
    assert epochs() == before


# --- T10: the step-boundary invariant hand-over relies on ---


def test_a_stamp_serving_the_execution_never_names_a_run_with_a_step_in_flight(ladder):
    ladder.submit()
    stamped_id = ladder.session.run_id
    ladder.run_tier(CONTINUE)
    result_wire = ladder.execute_tier(CONTINUE)
    node = ladder.orchestrator.nodes[ladder.scope]
    generation = node.execution_generation
    steps_built = len(ladder.submitted_work)

    # A reopen while the stamped run's step is in flight joins the running node:
    # no wire is built, so nothing stamps and nothing is handed over mid-step.
    ladder.close_stream()
    winner_id = ladder.open_stream().run_id
    ladder.submit(force_fresh=True)
    assert len(ladder.submitted_work) == steps_built
    assert node.execution_generation == generation
    assert get_row_run(stamped_id) is not None

    ladder.complete_tier(result_wire)
    ladder.run_tier(CONTINUE)

    assert ladder.tier_steps == [(stamped_id, 0), (stamped_id, 1), (winner_id, 2)]
    assert get_row_run(stamped_id) is None


# --- The scheduler plane forgets retired runs ---


def test_forget_runs_drops_only_the_retired_runs_scheduler_entries(ladder):
    retired_id = ladder.session.run_id
    ladder.close_stream()
    winner = ladder.open_stream()
    scheduler = ladder.scheduler
    scheduler._runs[retired_id] = ladder.scope
    scheduler._execution_generation_by_run_id[retired_id] = 3
    scheduler._execution_generation_by_run_id[winner.run_id] = 3
    accepted: list[str] = []
    scheduler._pending_accepts.register(retired_id, lambda: accepted.append(retired_id))
    scheduler._pending_accepts.register(winner.run_id, lambda: accepted.append(winner.run_id))
    held = HeldTierSubmission(
        stream_token=ladder.stream_token,
        binding=InferenceStreamOrchestratorBinding(
            orchestrator=ladder.orchestrator, query_context=ladder.ctx
        ),
        root_scope=ladder.scope,
    )
    scheduler._held_initial_submissions.append(held)

    scheduler.forget_runs((retired_id,))

    assert retired_id not in scheduler._runs
    assert retired_id not in scheduler._execution_generation_by_run_id
    assert scheduler._runs[winner.run_id] == ladder.scope
    assert scheduler._execution_generation_by_run_id[winner.run_id] == 3
    assert scheduler._held_initial_submissions == [held]
    scheduler.accept_pending_run(retired_id)
    scheduler.accept_pending_run(winner.run_id)
    assert accepted == [winner.run_id]

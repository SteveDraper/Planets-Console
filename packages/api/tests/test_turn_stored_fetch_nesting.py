"""Turn-stored reschedules run after the filling submit's root plans close.

A submit fills its dependency chain from one frame, and every turn it fetches
runs the real turn-stored hook (``TurnLoadService`` -> ``TurnStoredFanOut`` ->
scores, fleet and homeworld). The scores wake that hook hands over is held
until the submit's root-plan block closes, so turn fetches nest at most once
per fill caller and twice for a storer outside a root plan, however many turns
are missing.

The harness:

- a real orchestrator, installed as the process orchestrator before the scores
  stream binds, whose pool records steps and runs none;
- the real service stack on a memory backend, with a fake Planets.nu client,
  so every fetch goes through ``ensure_turn_loaded`` and the stack's hook;
- an open scores stream at the sample turn H, whose rows run on that
  orchestrator, planned as their root node alone;
- the outer submits are the self-chained fixture analytic, which plans for
  real; a scores row's chain fill is that fixture's chain at the row's turn,
  so a re-admit that finds holes fetches them through the same hook;
- fetch nesting counted as 1 plus the hook frames active on the fetching
  thread, and the stack depth at each fetch.
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, replace

import pytest
from api.analytics.export_turn_fill import DependencyChainFillError
from api.analytics.export_types import ExportScope
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.homeworld_locator.persistence import HomeworldLocatorPersistenceService
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_scope import (
    scores_root_scope_for_session,
)
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.scores import REGISTRATION as SCORES_REGISTRATION
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute import ComputeOrchestrator, ComputeRequest, build_compute_registry
from api.compute.errors import ComputeScopeAbortedError
from api.compute.pools import reset_compute_worker_pool_for_tests
from api.models.turn_write import TurnWrite
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.turn_stored_fan_out import TurnStoredInvalidationError
from api.streaming.table_stream import stream_drain

from tests.compute_orchestrator_fixtures import (
    ArmableRootPlanHook,
    RecordingPoolSubmitter,
    inline_compute_registration,
    make_compute_scope,
)
from tests.contained_callback_guard import CONTAINMENT_LOGGER
from tests.fixtures.export_framework.chain_exports import CHAIN_ID
from tests.fixtures.export_framework.harness import CHAIN_FIXTURE_EXPORT_REGISTRY
from tests.fixtures.export_framework.state import FIXTURE_EXPORT_STATE
from tests.scores_row_lifecycle_test_helpers import (
    attach_active_table_stream,
    patch_scores_only_dag,
)
from tests.table_stream_test_helpers import end_stream_inline
from tests.turn_stored_harness_helpers import (
    DEFAULT_RECURSION_LIMIT,
    GAME_ID,
    PERSPECTIVE,
    StoredGame,
    TurnSource,
    build_stored_game,
    record_calls,
    stack_depth,
    turn_of_ids_call,
    turn_of_write_call,
)

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")


def _chain_ctx(game: StoredGame, turn_number: int):
    """The login-backed query context the stack builds, over the chain fixture's catalog."""
    return game.query_context(turn_number, export_registry=CHAIN_FIXTURE_EXPORT_REGISTRY)


@dataclass(frozen=True)
class _Harness:
    game: StoredGame
    orchestrator: ComputeOrchestrator
    chain_root_plan: ArmableRootPlanHook
    scheduler: InferenceRowScheduler
    stream: InferenceTableStreamController

    @property
    def stream_turn(self) -> int:
        return self.game.turns.sample_turn.settings.turn

    def submit_chain(self, turn_number: int):
        scope = make_compute_scope(
            CHAIN_ID,
            ExportScope(
                game_id=GAME_ID,
                perspective=PERSPECTIVE,
                turn=turn_number,
                player_id=self.stream_player_ids()[0],
            ),
        )
        return self.orchestrator.submit(
            ComputeRequest(ctx=_chain_ctx(self.game, turn_number), scope=scope)
        )

    def stream_player_ids(self) -> tuple[int, ...]:
        return tuple(self.stream.scheduled_rows)

    def stream_run_ids(self) -> dict[int, str]:
        return {
            player_id: row.session.run_id for player_id, row in self.stream.scheduled_rows.items()
        }

    def is_live(self, run_id: str) -> bool:
        return run_id in self.scheduler._runs

    def stream_row_scope(self, player_id: int):
        return scores_root_scope_for_session(self.stream.scheduled_rows[player_id].session)

    def assert_stream_rows_re_admitted(self, before: dict[int, str]) -> None:
        """Every stream row has a new live run whose node is running, and the old runs ended."""
        after = self.stream_run_ids()
        assert set(after) == set(before)
        for player_id, run_id in after.items():
            assert run_id != before[player_id]
            assert self.is_live(run_id)
            assert not self.is_live(before[player_id])
            assert self.orchestrator.nodes[self.stream_row_scope(player_id)].state == "running"


def _scores_chain_fill_through_fixture(game: StoredGame, monkeypatch) -> None:
    """Fill a scores row's chain as the chain fixture's chain at the row's turn."""
    import api.compute.orchestrator_submission as submission

    real_prepare = submission.prepare_dependency_chain_turns

    def prepare(ctx, analytic_id, export_scope, *, force_root=False, backfill_earlier_turns):
        if analytic_id == SCORES_ANALYTIC_ID:
            real_prepare(
                _chain_ctx(game, export_scope.turn),
                CHAIN_ID,
                export_scope,
                backfill_earlier_turns=False,
            )
            return
        real_prepare(
            ctx,
            analytic_id,
            export_scope,
            force_root=force_root,
            backfill_earlier_turns=backfill_earlier_turns,
        )

    monkeypatch.setattr(submission, "prepare_dependency_chain_turns", prepare)


@pytest.fixture
def harness(sample_turn, monkeypatch, make_inference_scheduler) -> Iterator[_Harness]:
    """The harness with turns 1..H stored and the scores stream at H open."""
    reset_inference_table_stream_registry_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)
    FIXTURE_EXPORT_STATE.reset()
    patch_scores_only_dag(monkeypatch)
    chain_root_plan = ArmableRootPlanHook()
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry(
            (
                replace(inline_compute_registration(CHAIN_ID), open_root_plan=chain_root_plan),
                SCORES_REGISTRATION,
            )
        ),
        pool_submitter=RecordingPoolSubmitter(),
    )
    monkeypatch.setattr("api.compute.runtime._process_orchestrator", orchestrator)
    game = build_stored_game(TurnSource(sample_turn), monkeypatch)
    _scores_chain_fill_through_fixture(game, monkeypatch)
    game.store_turns(range(1, sample_turn.settings.turn + 1))
    scheduler = make_inference_scheduler()
    player_ids = tuple(row.ownerid for row in sample_turn.scores[:2])
    stream, _rows, _wake = attach_active_table_stream(sample_turn, scheduler, player_ids)
    built = _Harness(
        game=game,
        orchestrator=orchestrator,
        chain_root_plan=chain_root_plan,
        scheduler=scheduler,
        stream=stream,
    )
    yield built
    end_stream_inline(built.scheduler, built.stream.scope, built.stream.stream_token)
    game.stack.analytics.shutdown_background_workers()
    reset_inference_table_stream_registry_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=1)


def _missing_up_to(harness: _Harness, host_turn: int, *, first_missing: int) -> None:
    """Store the host turn; turns from ``first_missing`` up to it are missing."""
    harness.game.forget_turns(range(first_missing, host_turn))
    harness.game.store_turns([host_turn])


def test_a_fill_through_the_stream_turn_nests_once_and_re_admits_after_the_plan(harness):
    stream_turn = harness.stream_turn
    _missing_up_to(harness, stream_turn + 2, first_missing=stream_turn - 2)
    before = harness.stream_run_ids()
    at_accept_plan: dict[str, object] = {}

    def record_stream_at_accept_plan() -> None:
        at_accept_plan["runs"] = harness.stream_run_ids()
        at_accept_plan["live"] = [harness.is_live(run_id) for run_id in before.values()]
        at_accept_plan["node_states"] = [
            harness.orchestrator.nodes[harness.stream_row_scope(player_id)].state
            for player_id in before
        ]

    harness.chain_root_plan.arm(on_accept_plan=record_stream_at_accept_plan)
    handle = harness.submit_chain(stream_turn + 2)

    assert handle.error is None
    assert harness.game.planets.fetched_turns() == list(range(stream_turn - 2, stream_turn + 2))
    assert set(harness.game.planets.nesting_by_turn().values()) == {1}
    # The hook cancelled the stream's rows and aborted their nodes before the
    # outer plan was accepted, and re-admitted nothing while it was open.
    assert at_accept_plan == {
        "runs": before,
        "live": [False, False],
        "node_states": ["failed", "failed"],
    }
    harness.assert_stream_rows_re_admitted(before)


def _drain_on_another_thread(orchestrator: ComputeOrchestrator, stop: threading.Event) -> None:
    while not stop.is_set():
        orchestrator.drain_post_lock_callbacks()
        stop.wait(0.001)


def test_the_accelerated_n_minus_1_fill_runs_on_the_filling_thread_after_the_plan(harness):
    stream_turn = harness.stream_turn
    first_reliable_turn = stream_turn + 1
    harness.game.turns.accelerated_turns = first_reliable_turn
    harness.game.store_turns(range(1, stream_turn + 1))
    harness.game.forget_turns(range(stream_turn - 5, stream_turn))
    _missing_up_to(harness, stream_turn + 2, first_missing=first_reliable_turn)
    before = harness.stream_run_ids()
    fetches_when_the_plan_closed: list[int] = []
    harness.chain_root_plan.arm(
        on_exit=lambda: fetches_when_the_plan_closed.extend(harness.game.planets.fetched_turns())
    )
    stop = threading.Event()
    drainer = threading.Thread(
        target=_drain_on_another_thread, args=(harness.orchestrator, stop), daemon=True
    )
    drainer.start()
    try:
        handle = harness.submit_chain(stream_turn + 2)
    finally:
        stop.set()
        drainer.join(timeout=10)

    assert handle.error is None
    # The outer scope is at or above N, so its floor is N and it fetches N alone.
    # The re-admit of the row at N-1 has floor 1 and fetches the holes below it.
    assert fetches_when_the_plan_closed == [first_reliable_turn]
    assert harness.game.planets.fetched_turns() == [
        first_reliable_turn,
        *range(stream_turn - 5, stream_turn),
    ]
    assert set(harness.game.planets.nesting_by_turn().values()) == {1}
    assert {fetch.thread for fetch in harness.game.planets.fetches} == {threading.get_ident()}
    harness.assert_stream_rows_re_admitted(before)


def test_held_re_admits_run_after_a_chain_fill_error(harness):
    stream_turn = harness.stream_turn
    _missing_up_to(harness, stream_turn + 2, first_missing=stream_turn - 2)
    harness.game.planets.failing_turns = {stream_turn + 1}
    before = harness.stream_run_ids()

    with pytest.raises(DependencyChainFillError) as error:
        harness.submit_chain(stream_turn + 2)

    assert error.value.missing_turn == stream_turn + 1
    assert harness.game.planets.fetched_turns() == list(range(stream_turn - 2, stream_turn + 2))
    harness.assert_stream_rows_re_admitted(before)


class _PlanRefused(RuntimeError):
    pass


def test_held_re_admits_run_after_the_outer_plan_is_refused(harness):
    stream_turn = harness.stream_turn
    _missing_up_to(harness, stream_turn + 2, first_missing=stream_turn - 2)
    before = harness.stream_run_ids()
    at_refusal: list[bool] = []

    def refuse() -> None:
        at_refusal.extend(harness.is_live(run_id) for run_id in harness.stream_run_ids().values())
        raise _PlanRefused("refused")

    harness.chain_root_plan.arm(on_accept_plan=refuse)

    with pytest.raises(_PlanRefused):
        harness.submit_chain(stream_turn + 2)

    assert at_refusal == [False, False]
    harness.assert_stream_rows_re_admitted(before)


def test_a_storer_outside_any_root_plan_nests_fetches_twice(harness):
    stream_turn = harness.stream_turn
    harness.game.forget_turns([stream_turn - 2, stream_turn - 1, stream_turn + 1])
    before = harness.stream_run_ids()

    harness.game.store_turn_outside_any_root_plan(stream_turn + 1)

    # The wake runs at once inside the hook; its submit fills the row's chain.
    assert harness.game.planets.nesting_by_turn() == {
        stream_turn + 1: 1,
        stream_turn - 2: 2,
        stream_turn - 1: 2,
    }
    assert harness.game.planets.fetched_turns() == [
        stream_turn + 1,
        stream_turn - 2,
        stream_turn - 1,
    ]
    harness.assert_stream_rows_re_admitted(before)


def test_every_invalidation_of_the_fill_precedes_the_first_re_admit(harness, monkeypatch):
    stream_turn = harness.stream_turn
    _missing_up_to(harness, stream_turn + 2, first_missing=stream_turn - 2)
    events: list[tuple[str, int]] = []
    record_calls(
        monkeypatch,
        FleetSnapshotPersistenceService,
        "invalidate_for_turn_write",
        turn_of_ids_call,
        events,
    )
    record_calls(
        monkeypatch,
        HomeworldLocatorPersistenceService,
        "invalidate_evidence_from_turn",
        turn_of_ids_call,
        events,
    )
    record_calls(
        monkeypatch, InferenceInvalidationService, "wake_for_turn_write", turn_of_write_call, events
    )

    harness.submit_chain(stream_turn + 2)

    fetched = list(range(stream_turn - 2, stream_turn + 2))
    wake = "InferenceInvalidationService.wake_for_turn_write"
    invalidations = [(kind, turn) for kind, turn in events if kind != wake]
    wakes = [turn for kind, turn in events if kind == wake]
    assert invalidations == [
        (kind, turn)
        for turn in fetched
        for kind in (
            "FleetSnapshotPersistenceService.invalidate_for_turn_write",
            "HomeworldLocatorPersistenceService.invalidate_evidence_from_turn",
        )
    ]
    assert wakes == fetched
    assert events[: len(invalidations)] == invalidations


class _InjectedFailure(RuntimeError):
    pass


_INVALIDATIONS = (
    (InferenceInvalidationService, "invalidate_for_turn_write", turn_of_write_call),
    (InferenceInvalidationService, "cancel_for_turn_write", turn_of_write_call),
    (FleetSnapshotPersistenceService, "invalidate_for_turn_write", turn_of_ids_call),
    (HomeworldLocatorPersistenceService, "invalidate_evidence_from_turn", turn_of_ids_call),
)


@pytest.mark.allows_contained_callback_errors
@pytest.mark.parametrize(("owner", "method", "turn_of"), _INVALIDATIONS)
def test_a_failed_invalidation_reaches_the_fill_caller_after_every_consumer_ran(
    harness, monkeypatch, owner, method, turn_of
):
    stream_turn = harness.stream_turn
    _missing_up_to(harness, stream_turn + 2, first_missing=stream_turn - 2)
    before = harness.stream_run_ids()
    events: list[tuple[str, int]] = []
    for other_owner, other_method, other_turn_of in _INVALIDATIONS:
        if (other_owner, other_method) != (owner, method):
            record_calls(monkeypatch, other_owner, other_method, other_turn_of, events)
    real = getattr(owner, method)

    def fail_at_the_stream_turn(self, *args):
        if turn_of(args) == stream_turn:
            raise _InjectedFailure(method)
        return real(self, *args)

    monkeypatch.setattr(owner, method, fail_at_the_stream_turn)

    with pytest.raises(TurnStoredInvalidationError) as error:
        harness.submit_chain(stream_turn + 2)

    # The stream turn's hook raises after its turn is stored, and the fill stops there.
    assert isinstance(error.value.__cause__, _InjectedFailure)
    assert error.value.write == TurnWrite(GAME_ID, PERSPECTIVE, stream_turn)
    assert harness.game.planets.fetched_turns() == list(range(stream_turn - 2, stream_turn + 1))
    assert harness.game.stack.turns.is_turn_stored(GAME_ID, PERSPECTIVE, stream_turn)
    assert [name for name, turn in events if turn == stream_turn] == [
        f"{other_owner.__name__}.{other_method}"
        for other_owner, other_method, _turn_of in _INVALIDATIONS
        if (other_owner, other_method) != (owner, method)
    ]
    harness.assert_stream_rows_re_admitted(before)


@pytest.mark.allows_contained_callback_errors
def test_a_failed_held_re_admit_is_contained_and_logged(harness, monkeypatch, caplog):
    stream_turn = harness.stream_turn
    _missing_up_to(harness, stream_turn + 2, first_missing=stream_turn - 2)

    def fail(self, write: TurnWrite) -> None:
        raise _InjectedFailure(f"re-admit at {write.turn_number}")

    monkeypatch.setattr(InferenceInvalidationService, "wake_for_turn_write", fail)

    with caplog.at_level(logging.ERROR, logger=CONTAINMENT_LOGGER):
        handle = harness.submit_chain(stream_turn + 2)

    assert handle.error is None
    failures = [
        record.exc_info[1]
        for record in caplog.records
        if record.name == CONTAINMENT_LOGGER and record.exc_info is not None
    ]
    assert [str(failure) for failure in failures] == [
        f"re-admit at {turn}" for turn in range(stream_turn - 2, stream_turn + 2)
    ]


def test_the_stale_run_is_aborted_before_the_outer_plan_and_re_admitted_after(harness, monkeypatch):
    stream_turn = harness.stream_turn
    _missing_up_to(harness, stream_turn + 2, first_missing=stream_turn + 1)
    before = harness.stream_run_ids()
    old_scopes = {harness.stream_row_scope(player_id) for player_id in before}
    events: list[tuple[str, int]] = []
    harness.orchestrator.observers.register_scope_outcome_listener(
        lambda snapshot: (
            events.append(("abort", snapshot.scope.turn)) if snapshot.is_intentional_abort else None
        )
    )
    record_calls(
        monkeypatch, InferenceInvalidationService, "wake_for_turn_write", turn_of_write_call, events
    )
    at_accept_plan: list[object] = []

    def record_old_nodes() -> None:
        for scope in old_scopes:
            node = harness.orchestrator.nodes[scope]
            at_accept_plan.append((node.state, type(node.error)))
        at_accept_plan.append(list(events))

    harness.chain_root_plan.arm(on_accept_plan=record_old_nodes)

    harness.submit_chain(stream_turn + 2)

    # The old nodes were aborted before the outer plan registered, with their
    # listeners still queued; they ran at the exit, before the held re-admit.
    assert at_accept_plan == [("failed", ComputeScopeAbortedError)] * len(old_scopes) + [[]]
    assert events == [("abort", stream_turn)] * len(old_scopes) + [
        ("InferenceInvalidationService.wake_for_turn_write", stream_turn + 1)
    ]
    harness.assert_stream_rows_re_admitted(before)
    assert not any(stream_drain.is_closed(run_id) for run_id in harness.stream_run_ids().values())
    assert [
        event
        for event in harness.stream.drain_pending_wire_events()
        if event.get("type") in {"complete", "error"}
    ] == []


# --- Frame depth ---

SHORT_CHAIN_TURNS = 50
LONG_CHAIN_TURNS = 300


@dataclass
class _ChainDepths:
    fetch_depths: list[int]
    deepest_walk: int


def _fill_a_chain(harness: _Harness, monkeypatch, chain_turns: int) -> _ChainDepths:
    """Fill every turn below a chain of ``chain_turns`` turns; record fetch and walk depths."""
    deepest = [0]
    real_is_persisted = FIXTURE_EXPORT_STATE.is_persisted

    def is_persisted(analytic_id, scope) -> bool:
        deepest[0] = max(deepest[0], stack_depth())
        return real_is_persisted(analytic_id, scope)

    monkeypatch.setattr(FIXTURE_EXPORT_STATE, "is_persisted", is_persisted)
    harness.game.planets.fetches.clear()
    harness.game.forget_turns(range(2, chain_turns))
    harness.game.store_turns([chain_turns])
    base = stack_depth()

    handle = harness.submit_chain(chain_turns)

    assert handle.error is None
    assert harness.game.planets.fetched_turns() == list(range(2, chain_turns))
    assert set(harness.game.planets.nesting_by_turn().values()) == {1}
    return _ChainDepths(
        fetch_depths=[fetch.stack_depth - base for fetch in harness.game.planets.fetches],
        deepest_walk=deepest[0] - base,
    )


def test_a_long_fill_stays_under_the_default_recursion_limit(harness, monkeypatch):
    assert sys.getrecursionlimit() == DEFAULT_RECURSION_LIMIT

    short = _fill_a_chain(harness, monkeypatch, SHORT_CHAIN_TURNS)
    FIXTURE_EXPORT_STATE.reset()
    long = _fill_a_chain(harness, monkeypatch, LONG_CHAIN_TURNS)

    # Each fetch runs from the fill's own frame, at one depth however long the chain.
    assert set(short.fetch_depths) == set(long.fetch_depths)
    assert len(set(long.fetch_depths)) == 1
    # Only the dependency walk grows with the chain, by a constant per level.
    frames_per_level = (long.deepest_walk - short.deepest_walk) / (
        LONG_CHAIN_TURNS - SHORT_CHAIN_TURNS
    )
    assert frames_per_level == int(frames_per_level)
    assert long.deepest_walk < DEFAULT_RECURSION_LIMIT

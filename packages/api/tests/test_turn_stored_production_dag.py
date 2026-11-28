"""Turn-stored reschedules on the production fleet and scores DAG.

The harness runs the real service stack (a memory backend, a fake Planets.nu
client, the stack's turn-stored hook) on the process orchestrator, whose pool
has no workers: ``run_recorded`` runs the queued steps on the test thread in
pick order, each completion draining here. Backfill earlier turns is on, so
fleet and scores scopes ensure the prior final fleet, and a shell is an
on-walk that assumes the ensure baseline mark while its root plan is open. A
real scores table stream is open at H for one player.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace

import pytest
from api.analytics.export_turn_fill import DependencyChainFillError
from api.analytics.fleet.evidence_mark_store import FleetEvidenceMarkStore
from api.analytics.fleet.fleet_table_stream_registry import (
    reset_fleet_table_stream_registry_for_tests,
)
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.military_score_inference.inference_table_stream_registry import (
    controller_for_scope,
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.scores.tier_row_run_registry import decide_scores_row_persist
from api.compute import ComputeOrchestrator, ComputeRequest
from api.compute.pools import ComputeWorkerPool, reset_compute_worker_pool_for_tests
from api.compute.runtime import get_compute_orchestrator
from api.compute.scope import ComputeScope
from api.config import get_config, set_config
from api.errors import NotFoundError
from api.models.turn_write import TurnWrite
from api.serialization.backfill_earlier_turns import (
    backfill_earlier_turns_document,
    backfill_earlier_turns_store_key,
)
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.streaming.table_stream import stream_drain

from tests.off_mode_catch_up_helpers import player_ledger
from tests.scores_exports_helpers import inference_target_player_id
from tests.table_stream_test_helpers import end_stream_inline
from tests.turn_stored_harness_helpers import (
    DEFAULT_RECURSION_LIMIT,
    GAME_ID,
    PERSPECTIVE,
    USERNAME,
    StoredGame,
    TurnSource,
    build_stored_game,
    stack_depth,
)

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")

STREAM_TURN = 6
WAIT_SECONDS = 20.0


@dataclass
class _ScoresStream:
    """A real scores table stream at the stream turn, consumed on its own thread."""

    events: list[dict[str, object]] = field(default_factory=list)
    thread: threading.Thread | None = None

    def terminals_after(self, start: int) -> list[dict[str, object]]:
        return [
            event for event in self.events[start:] if event.get("type") in {"complete", "error"}
        ]


@dataclass
class _ProductionDag:
    game: StoredGame
    pool: ComputeWorkerPool
    orchestrator: ComputeOrchestrator
    player_id: int
    stream: _ScoresStream = field(default_factory=_ScoresStream)

    @property
    def scores_scheduler(self) -> InferenceRowScheduler:
        return self.game.query_context(STREAM_TURN).export_services["scores"].scheduler

    @property
    def fleet(self) -> FleetSnapshotPersistenceService:
        return self.game.query_context(STREAM_TURN).export_services["fleet"].persistence

    def set_backfill_earlier_turns(self, enabled: bool) -> None:
        self.game.storage.put(
            backfill_earlier_turns_store_key(GAME_ID), backfill_earlier_turns_document(enabled)
        )

    def scope(self, analytic_id: str, turn: int) -> ComputeScope:
        return ComputeScope(
            analytic_id=analytic_id,
            game_id=GAME_ID,
            perspective=PERSPECTIVE,
            turn=turn,
            player_id=self.player_id,
        )

    def request(self, analytic_id: str, turn: int) -> ComputeRequest:
        return ComputeRequest(
            ctx=self.game.query_context(turn), scope=self.scope(analytic_id, turn)
        )

    def open_stream(self) -> None:
        """Open the stream as the SPA does, and wait until its row has a node."""
        events = self.game.stack.analytics.iter_scores_table_inference_stream(
            GAME_ID, PERSPECTIVE, STREAM_TURN, (self.player_id,), username=USERNAME
        )
        self.stream.events.append(next(events))

        def consume() -> None:
            try:
                for event in events:
                    self.stream.events.append(event)
            finally:
                events.close()

        self.stream.thread = threading.Thread(target=consume, name="scores-stream", daemon=True)
        self.stream.thread.start()
        _wait_until(lambda: self.scope("scores", STREAM_TURN) in self.orchestrator.nodes)

    @property
    def controller(self) -> InferenceTableStreamController:
        controller = controller_for_scope(InferenceStreamScope(GAME_ID, PERSPECTIVE, STREAM_TURN))
        assert controller is not None
        return controller

    def end_stream_once_its_row_is_read(self) -> None:
        """End the stream once its row's terminal is read and nothing is pending; join it.

        Call once compute is idle, so nothing further can reach the stream. The
        stream closes a run as it reads the run's terminal, and yields every
        pending event it has taken before it checks whether the stream is still
        open. So after the consumer thread ends, ``events`` holds everything the
        stream read.
        """
        controller = self.controller
        bound_run_id = self.bound_run_id()
        _wait_until(
            lambda: stream_drain.is_closed(bound_run_id) and not controller.pending_wire_events,
            "the stream never read the bound run's terminal",
        )
        end_stream_inline(self.scores_scheduler, controller.scope, controller.stream_token)
        assert self.stream.thread is not None
        self.stream.thread.join(timeout=WAIT_SECONDS)
        assert not self.stream.thread.is_alive(), "the stream consumer did not end with the stream"

    def bound_run_id(self) -> str:
        return self.controller.scheduled_rows[self.player_id].session.run_id

    def run_recorded(self, *, hold: Callable[[ComputeScope, str], bool] = lambda *_: False) -> None:
        """Run queued steps on this thread until none is left but the held ones."""
        held = []
        while (picked := self.pool.take_next_item_for_tests()) is not None:
            if hold(picked.item.scope, picked.item.step_kind):
                held.append(picked.item)
                continue
            self.pool._execute_item(picked)
        for item in held:
            self.pool.enqueue_for_tests(item)

    def run_until(self, thread: threading.Thread) -> None:
        """Run queued steps until ``thread`` (waiting on them) ends, then until idle."""
        deadline = time.monotonic() + WAIT_SECONDS
        while thread.is_alive() and time.monotonic() < deadline:
            self.run_recorded()
            thread.join(timeout=0.01)
        assert not thread.is_alive()
        self.run_recorded()

    def hold_the_stream_row_tier_solve(self) -> None:
        """Run everything but the stream row's own solve, so its old run is still running."""
        stream_scope = self.scope("scores", STREAM_TURN)
        self.run_recorded(hold=lambda scope, step_kind: scope == stream_scope)
        assert self.orchestrator.nodes[stream_scope].state == "running"

    def is_mark_stored(self) -> bool:
        """Whether the player's mark is stored, read past any assumed mark."""
        try:
            self.game.storage.get(FleetEvidenceMarkStore.key(GAME_ID, PERSPECTIVE, self.player_id))
        except NotFoundError:
            return False
        return True


def _wait_until(predicate: Callable[[], bool], failure: str = "condition not met") -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while not predicate():
        assert time.monotonic() < deadline, f"{failure} within {WAIT_SECONDS}s"
        time.sleep(0.01)


@pytest.fixture
def dag(sample_turn, monkeypatch) -> Iterator[_ProductionDag]:
    reset_inference_table_stream_registry_for_tests()
    reset_fleet_table_stream_registry_for_tests()
    pool = reset_compute_worker_pool_for_tests(worker_count=0)
    set_config(replace(get_config(), remap_interpreter_backend_to_thread=True))
    orchestrator = get_compute_orchestrator(worker_pool=pool)
    turns = TurnSource(
        sample_turn,
        accelerated_turns=sample_turn.settings.acceleratedturns,
        quiet_scoreboard=True,
    )
    game = build_stored_game(turns, monkeypatch)
    game.store_turns(range(1, STREAM_TURN + 1))
    built = _ProductionDag(
        game=game,
        pool=pool,
        orchestrator=orchestrator,
        player_id=inference_target_player_id(turns.turn_at(STREAM_TURN)),
    )
    built.set_backfill_earlier_turns(True)
    yield built
    reset_inference_table_stream_registry_for_tests()
    reset_fleet_table_stream_registry_for_tests()
    game.stack.analytics.shutdown_background_workers()
    if built.stream.thread is not None:
        built.stream.thread.join(timeout=2.0)


@dataclass
class _WakeRecord:
    turn: int
    is_mark_stored: bool
    mark_seen: object
    scores_node_state: str | None


def _record_wakes(dag: _ProductionDag, monkeypatch) -> tuple[list[_WakeRecord], threading.Event]:
    """Record what each scores wake sees as it starts; set the event as each one returns."""
    wakes: list[_WakeRecord] = []
    woke = threading.Event()
    real_wake = InferenceInvalidationService.wake_for_turn_write
    stream_scope = dag.scope("scores", STREAM_TURN)

    def wake(self, write: TurnWrite) -> None:
        node = dag.orchestrator.nodes.get(stream_scope)
        wakes.append(
            _WakeRecord(
                turn=write.turn_number,
                is_mark_stored=dag.is_mark_stored(),
                mark_seen=dag.fleet.evidence_mark(GAME_ID, PERSPECTIVE, dag.player_id),
                scores_node_state=None if node is None else node.state,
            )
        )
        try:
            real_wake(self, write)
        finally:
            woke.set()

    monkeypatch.setattr(InferenceInvalidationService, "wake_for_turn_write", wake)
    return wakes, woke


def _record_stream_run_registrations(monkeypatch, turn: int) -> list[str]:
    """Run ids of every scores row run registered at ``turn``, in order."""
    registered: list[str] = []
    real_enqueue = InferenceRowScheduler.enqueue_tier_ladder

    def enqueue(self, session, *args, **kwargs):
        if session.turn_number == turn:
            registered.append(session.run_id)
        return real_enqueue(self, session, *args, **kwargs)

    monkeypatch.setattr(InferenceRowScheduler, "enqueue_tier_ladder", enqueue)
    return registered


# --- Case 7: the stale run during the fill ---


@pytest.mark.parametrize(
    ("order", "expected_registrations"),
    [
        # scores@H is dispatchable at the exit drain: its export admit registers
        # a STREAM run first, and the held re-admit then registers a newer one.
        ("dispatchable", 2),
        # scores@H waits on fleet@H-1: the re-admit registers first, and the
        # later export admit finds its run.
        ("waiting on fleet", 1),
    ],
)
def test_the_stale_run_is_replaced_and_both_orders_converge(
    dag, monkeypatch, order, expected_registrations
):
    dag.open_stream()
    dag.hold_the_stream_row_tier_solve()
    old_run_id = dag.bound_run_id()
    old_node = dag.orchestrator.nodes[dag.scope("scores", STREAM_TURN)]
    if order == "waiting on fleet":
        dag.fleet.delete_ledger(GAME_ID, PERSPECTIVE, STREAM_TURN - 1, dag.player_id)
    dag.game.store_turns([STREAM_TURN + 2])
    wakes, woke = _record_wakes(dag, monkeypatch)
    registered = _record_stream_run_registrations(monkeypatch, STREAM_TURN)
    events_before = len(dag.stream.events)
    outcome: dict[str, object] = {}

    def ensure() -> None:
        # One batch whose first root fills H+1 and whose second is scores@H.
        outcome["handles"] = dag.orchestrator.ensure_scopes(
            (dag.request("scores", STREAM_TURN + 2), dag.request("scores", STREAM_TURN)),
            timeout=WAIT_SECONDS,
        )

    ensurer = threading.Thread(target=ensure, name="ensure", daemon=True)
    ensurer.start()
    assert woke.wait(WAIT_SECONDS)
    dag.run_until(ensurer)

    assert dag.game.planets.fetched_turns() == [STREAM_TURN + 1]
    assert [handle.state for handle in outcome["handles"]] == ["complete", "complete"]
    # The old node was aborted by the hook and replaced by the outer before the
    # held re-admit ran; its run's persist is refused, so no evidence from it
    # reached the scores row or any fleet ledger finalized on it.
    assert old_node.state == "failed"
    assert dag.orchestrator.nodes[dag.scope("scores", STREAM_TURN)] is not old_node
    assert not decide_scores_row_persist(old_run_id).allowed
    expected_state_at_wake = "running" if order == "dispatchable" else "waiting_deps"
    assert [wake.scores_node_state for wake in wakes] == [expected_state_at_wake]
    assert len(registered) == expected_registrations
    # One terminal per player, no hung row, and the re-admit's run is bound.
    bound_run_id = dag.bound_run_id()
    controller_scope = dag.controller.scope
    dag.end_stream_once_its_row_is_read()
    (terminal,) = dag.stream.terminals_after(events_before)
    assert dag.stream.events[-1] == terminal
    assert bound_run_id == registered[-1]
    assert dag.scores_scheduler.row_run_for_player(controller_scope, dag.player_id) is None
    assert dag.fleet.has_final_ledger(GAME_ID, PERSPECTIVE, STREAM_TURN, dag.player_id)


# --- Cases 1 and 3: the evidence mark the held wake sees ---


def _open_the_stream_off_any_walk(dag: _ProductionDag) -> None:
    """Open the stream with Backfill earlier turns off and run nothing, so no mark is stored.

    Then turn the setting on for the outer submit.
    """
    dag.set_backfill_earlier_turns(False)
    dag.open_stream()
    assert not dag.is_mark_stored()
    dag.set_backfill_earlier_turns(True)


def test_the_held_wake_sees_the_mark_the_outer_on_walk_stored(dag, monkeypatch):
    _open_the_stream_off_any_walk(dag)
    dag.game.store_turns([STREAM_TURN + 2])
    wakes, _woke = _record_wakes(dag, monkeypatch)

    dag.orchestrator.submit(dag.request("fleet", STREAM_TURN + 2))

    assert dag.game.planets.fetched_turns() == [STREAM_TURN + 1]
    stored = dag.fleet.evidence_mark(GAME_ID, PERSPECTIVE, dag.player_id)
    assert dag.is_mark_stored()
    # The wake ran after the outer plan stored its mark and its assumption ended.
    assert [(wake.turn, wake.is_mark_stored, wake.mark_seen) for wake in wakes] == [
        (STREAM_TURN + 1, True, stored)
    ]


class _MarkWriteRefused(RuntimeError):
    pass


def _refuse_the_first_mark_write(monkeypatch) -> None:
    """Refuse the outer on-walk's mark write, which refuses its plan; later writes land."""
    real_update = FleetSnapshotPersistenceService.update_evidence_mark
    refused: list[bool] = []

    def refuse_once(self, *args, **kwargs):
        if not refused:
            refused.append(True)
            raise _MarkWriteRefused("mark write refused")
        return real_update(self, *args, **kwargs)

    monkeypatch.setattr(FleetSnapshotPersistenceService, "update_evidence_mark", refuse_once)


@pytest.mark.parametrize("failure", ["chain fill error", "plan refused"])
def test_held_wakes_do_not_see_the_failed_outer_assumed_mark(dag, monkeypatch, failure):
    _open_the_stream_off_any_walk(dag)
    outer_turn = STREAM_TURN + 3
    dag.game.store_turns([outer_turn])
    if failure == "chain fill error":
        dag.game.planets.failing_turns = {STREAM_TURN + 2}
        expected_error: type[BaseException] = DependencyChainFillError
    else:
        _refuse_the_first_mark_write(monkeypatch)
        expected_error = _MarkWriteRefused
    wakes, _woke = _record_wakes(dag, monkeypatch)

    with pytest.raises(expected_error):
        dag.orchestrator.submit(dag.request("fleet", outer_turn))

    # Inside the outer plan the absent mark read as the assumed baseline. Each
    # held wake ran after that assumption ended: the first saw nothing stored,
    # and none saw an assumed mark (a later one may see what an earlier
    # re-admit's own plan stored).
    stored_before_failing = (
        [STREAM_TURN + 1] if failure == "chain fill error" else [STREAM_TURN + 1, STREAM_TURN + 2]
    )
    assert [wake.turn for wake in wakes] == stored_before_failing
    assert not wakes[0].is_mark_stored
    assert all(wake.mark_seen.is_absent is not wake.is_mark_stored for wake in wakes)


# --- Case 5: the wake registers work against the bumped epoch ---


def test_fleet_work_the_wake_registers_is_not_refused(dag, monkeypatch):
    dag.open_stream()
    dag.run_recorded()
    prior_turn = STREAM_TURN - 1
    assert dag.fleet.has_final_ledger(GAME_ID, PERSPECTIVE, prior_turn, dag.player_id)
    # The re-admit must rebuild fleet@H-1, and the stored turn's invalidation
    # deletes a ledger of the player above it, which bumps the player's epoch.
    dag.fleet.delete_ledger(GAME_ID, PERSPECTIVE, prior_turn, dag.player_id)
    dag.fleet.put_ledger(
        GAME_ID,
        PERSPECTIVE,
        STREAM_TURN + 1,
        dag.player_id,
        player_ledger(dag.player_id, ship_id=1),
    )
    epoch_before = dag.fleet.player_invalidation_generation(GAME_ID, PERSPECTIVE, dag.player_id)
    prior_fleet_scope = dag.scope("fleet", prior_turn)
    stream_scope = dag.scope("scores", STREAM_TURN)
    epoch_at_re_admit: list[int] = []

    def record_epoch_when_the_re_admit_registers(kind, scope, *_rest) -> None:
        # The re-admit replaces the row's node, and plans fleet@H-1 in the same hold.
        if kind == "force_fresh_replace" and scope == stream_scope:
            epoch_at_re_admit.append(
                dag.fleet.player_invalidation_generation(GAME_ID, PERSPECTIVE, dag.player_id)
            )

    dag.orchestrator.observers.register_lifecycle_listener(record_epoch_when_the_re_admit_registers)

    dag.game.store_turn_outside_any_root_plan(STREAM_TURN + 1)
    dag.run_recorded()

    # The wake registered its work after the invalidation bumped the epoch,
    # so the fleet@H-1 it planned lands instead of being refused as stale.
    epoch_after = dag.fleet.player_invalidation_generation(GAME_ID, PERSPECTIVE, dag.player_id)
    assert epoch_after > epoch_before
    assert epoch_at_re_admit == [epoch_after]
    assert dag.orchestrator.nodes[prior_fleet_scope].state == "complete"
    assert dag.fleet.has_final_ledger(GAME_ID, PERSPECTIVE, prior_turn, dag.player_id)


# --- Frame depth with the production catalogs ---

SHORT_CHAIN_TURNS = 50
LONG_CHAIN_TURNS = 300


def _deepest_walk_level_while_filling(dag: _ProductionDag, monkeypatch, chain_turns: int) -> int:
    """Fill and plan fleet@chain_turns from its floor; return the walk's deepest stack.

    The depth is sampled where the dependency walk reads each scope's turn floor,
    which it does once per dependency edge at every level.
    """
    import api.analytics.export_dependency_walk as dependency_walk

    deepest = [0]
    real_floor = dependency_walk.ensure_dependency_turn_floor

    def ensure_dependency_turn_floor(ctx, scope):
        deepest[0] = max(deepest[0], stack_depth())
        return real_floor(ctx, scope)

    monkeypatch.setattr(
        dependency_walk, "ensure_dependency_turn_floor", ensure_dependency_turn_floor
    )
    dag.game.planets.fetches.clear()
    dag.game.store_turns([chain_turns])
    floor = dag.game.turns.sample_turn.settings.acceleratedturns
    missing = [
        turn
        for turn in range(floor, chain_turns)
        if not dag.game.stack.turns.is_turn_stored(GAME_ID, PERSPECTIVE, turn)
    ]
    base = stack_depth()

    dag.orchestrator.submit(dag.request("fleet", chain_turns))

    assert dag.game.planets.fetched_turns() == missing
    assert set(dag.game.planets.nesting_by_turn().values()) == {1}
    monkeypatch.setattr(dependency_walk, "ensure_dependency_turn_floor", real_floor)
    return deepest[0] - base


def test_the_production_walk_of_a_long_chain_stays_under_the_default_limit(dag, monkeypatch):
    assert sys.getrecursionlimit() == DEFAULT_RECURSION_LIMIT

    short = _deepest_walk_level_while_filling(dag, monkeypatch, SHORT_CHAIN_TURNS)
    long = _deepest_walk_level_while_filling(dag, monkeypatch, LONG_CHAIN_TURNS)

    frames_per_level = (long - short) / (LONG_CHAIN_TURNS - SHORT_CHAIN_TURNS)
    assert frames_per_level == int(frames_per_level)
    assert long < DEFAULT_RECURSION_LIMIT

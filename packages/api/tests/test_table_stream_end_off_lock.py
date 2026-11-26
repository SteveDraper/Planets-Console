"""A table stream's connect ``finally`` only posts its end; the scheduler's runner runs it.

The ``finally`` can run during garbage collection or when the generator's last
reference drops, on a thread that already holds a lock the end takes. Ending a
stream on a thread that holds any such lock must return, and the end then runs
on the scheduler's off-lock runner once the lock is free.
"""

from __future__ import annotations

import gc
import threading
from collections.abc import Callable, Iterator

import pytest
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.fleet_table_player_run import (
    FleetLedgerWireProgressTracker,
    FleetPlayerStreamSession,
)
from api.analytics.fleet.fleet_table_stream_scheduler import (
    FLEET_OFF_LOCK_THREAD_NAME,
    FleetTableStreamScheduler,
    _FleetPlayerOrchestratorRun,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.military_score_inference.inference_scheduler import (
    SCORES_OFF_LOCK_THREAD_NAME,
    InferenceRowScheduler,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.scores import tier_row_run_registry
from api.compute.runtime import get_compute_orchestrator
from api.compute.scope import ComputeScope
from api.streaming.table_stream.registry import TableStreamRegistry
from api.streaming.table_stream.scoped_connect import iter_table_stream_connect_with_scope
from api.streaming.table_stream.stream_scheduler import TableStreamScheduler

from tests.scores_exports_helpers import GAME_ID, perspective
from tests.scores_ladder_helpers import ladder_session
from tests.table_stream_test_helpers import IdleConnectPolicy

WAIT_SECONDS = 2.0
# A stream end that runs inside the ``finally`` deadlocks the thread holding the
# lock, and nothing in the process can release that lock again. The timeout's
# thread method dumps every thread's stack and ends the run, which is why the
# deadlock must surface inside the test call: pytest-timeout stops its timer
# once a test call fails, so a hang in teardown would never end.
DEADLOCK_TIMEOUT_SECONDS = 10

pytestmark = [
    pytest.mark.usefixtures("no_scores_row_runs"),
    pytest.mark.timeout(DEADLOCK_TIMEOUT_SECONDS, method="thread"),
]


def _connect(scheduler: TableStreamScheduler, scope: object, policy: IdleConnectPolicy) -> Iterator:
    stream = iter_table_stream_connect_with_scope(
        scheduler=scheduler,
        scope=scope,
        policy_factory=lambda _token: policy,
        player_ids=(),
    )
    assert next(stream) == {"type": "open"}
    return stream


def _close(stream: Iterator) -> Callable[[], None]:
    return stream.close


def _drop_last_reference(stream: Iterator) -> Callable[[], None]:
    box = [stream]

    def end() -> None:
        box.clear()

    return end


def _collect_cycle(stream: Iterator) -> Callable[[], None]:
    """Make ``stream`` cyclic garbage; the returned callable collects it."""
    cycle: list[object] = [stream]
    cycle.append(cycle)
    holder = [cycle]
    del cycle

    def end() -> None:
        holder.clear()
        gc.collect()

    return end


ENDINGS: dict[str, Callable[[Iterator], Callable[[], None]]] = {
    "close": _close,
    "drop last reference": _drop_last_reference,
    "collect cycle": _collect_cycle,
}


def _end_while_holding(lock_context: Callable[[], object], end: Callable[[], None]) -> None:
    """Run ``end`` on a thread that holds the lock, and wait for that thread.

    The wait has no timeout of its own, so an end that deadlocks under the lock
    hangs here, inside the test call, where the module timeout catches it.
    """

    def holder() -> None:
        with lock_context():
            end()

    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    thread.join()


# --- scores -------------------------------------------------------------------


@pytest.fixture
def scores(sample_turn, make_inference_scheduler):
    scheduler = make_inference_scheduler(defer_orchestrator_submit=True)
    scope = InferenceStreamScope(
        game_id=GAME_ID, perspective=perspective(sample_turn), turn_number=sample_turn.settings.turn
    )
    return scheduler, scope


def _scores_locks(scheduler: InferenceRowScheduler, session) -> dict[str, Callable[[], object]]:
    return {
        "scheduler lock": lambda: scheduler._lock,
        "row-run registry lock": lambda: tier_row_run_registry._lock,
        "pending accepts lock": lambda: scheduler._pending_accepts._lock,
        "session event queue mutex": lambda: session.event_queue.mutex,
        "orchestrator condition": lambda: get_compute_orchestrator()._condition,
    }


@pytest.mark.parametrize(
    "lock_name",
    [
        "scheduler lock",
        "row-run registry lock",
        "pending accepts lock",
        "session event queue mutex",
        "orchestrator condition",
    ],
)
@pytest.mark.parametrize("ending", sorted(ENDINGS))
def test_a_scores_stream_ends_while_its_thread_holds_a_teardown_lock(
    scores, sample_turn, lock_name, ending
) -> None:
    scheduler, scope = scores
    policy = IdleConnectPolicy()
    stream = _connect(scheduler, scope, policy)
    token = scheduler._scope_guard.active_table_stream_token
    session = ladder_session(sample_turn, sample_turn.scores[0].ownerid)
    scheduler.enqueue_tier_ladder(session, stream_token=token)
    end = ENDINGS[ending](stream)
    del stream

    _end_while_holding(_scores_locks(scheduler, session)[lock_name], end)

    assert scheduler.off_lock_runner.drain(timeout=WAIT_SECONDS)
    assert policy.detached
    assert not scheduler.owns_table_stream(token)
    assert session.run_id not in scheduler._runs


def test_a_paused_scores_stream_end_releases_on_the_runner(scores, monkeypatch) -> None:
    scheduler, scope = scores
    stream = _connect(scheduler, scope, IdleConnectPolicy())
    scheduler.pause_globally(scope)
    release_threads: list[str] = []
    monkeypatch.setattr(
        scheduler,
        "_dispatch_after_pause_cleared",
        lambda: release_threads.append(threading.current_thread().name),
    )

    stream.close()

    assert scheduler.off_lock_runner.drain(timeout=WAIT_SECONDS)
    assert scheduler.global_pause_status(scope)["paused"] is False
    assert release_threads == [SCORES_OFF_LOCK_THREAD_NAME]


def test_a_reopen_before_the_old_streams_end_runs_keeps_the_new_stream(scores) -> None:
    scheduler, scope = scores
    runner_free = threading.Event()
    stream = _connect(scheduler, scope, IdleConnectPolicy())
    old_token = scheduler._scope_guard.active_table_stream_token
    scheduler.pause_globally(scope)
    scheduler.off_lock_runner.post(lambda: runner_free.wait(WAIT_SECONDS))

    stream.close()
    new_token = scheduler.begin_scope(scope)
    scheduler.pause_globally(scope)
    runner_free.set()

    assert scheduler.off_lock_runner.drain(timeout=WAIT_SECONDS)
    assert old_token != new_token
    assert scheduler.owns_table_stream(new_token)
    assert scheduler.global_pause_status(scope)["paused"] is True


def test_a_raising_detach_still_posts_the_end(scores) -> None:
    scheduler, scope = scores
    stream = _connect(scheduler, scope, IdleConnectPolicy(detach_error=RuntimeError("detach")))
    token = scheduler._scope_guard.active_table_stream_token

    with pytest.raises(RuntimeError, match="detach"):
        stream.close()

    assert scheduler.off_lock_runner.drain(timeout=WAIT_SECONDS)
    assert not scheduler.owns_table_stream(token)


# --- fleet --------------------------------------------------------------------


@pytest.fixture
def fleet(make_fleet_table_stream_scheduler):
    return make_fleet_table_stream_scheduler(), FleetTableStreamScope(
        game_id=GAME_ID, perspective=1, turn_number=111
    )


def _install_fleet_run(scheduler: FleetTableStreamScheduler) -> FleetPlayerStreamSession:
    turn = type("Turn", (), {"settings": type("Settings", (), {"turn": 111})()})()
    session = FleetPlayerStreamSession(player_id=3, turn=turn, game_id=GAME_ID, perspective=1)
    scheduler._runs[session.run_id] = _FleetPlayerOrchestratorRun(
        session=session,
        host_turn_number=111,
        progress_tracker=FleetLedgerWireProgressTracker(host_turn=turn),
        root_scope=ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID, game_id=GAME_ID, perspective=1, turn=110, player_id=3
        ),
    )
    return session


@pytest.mark.parametrize(
    "lock_name",
    ["scheduler lock", "pending accepts lock", "cancel token lock", "orchestrator condition"],
)
@pytest.mark.parametrize("ending", sorted(ENDINGS))
def test_a_fleet_stream_ends_while_its_thread_holds_a_teardown_lock(
    fleet, lock_name, ending
) -> None:
    scheduler, scope = fleet
    policy = IdleConnectPolicy()
    stream = _connect(scheduler, scope, policy)
    token = scheduler._scope_guard.active_table_stream_token
    session = _install_fleet_run(scheduler)
    locks = {
        "scheduler lock": lambda: scheduler._lock,
        "pending accepts lock": lambda: scheduler._pending_accepts._lock,
        "cancel token lock": lambda: session.cancel_token._cancelled._cond,
        "orchestrator condition": lambda: get_compute_orchestrator()._condition,
    }
    end = ENDINGS[ending](stream)
    del stream

    _end_while_holding(locks[lock_name], end)

    assert scheduler.off_lock_runner.drain(timeout=WAIT_SECONDS)
    assert policy.detached
    assert not scheduler.owns_table_stream(token)
    assert session.run_id not in scheduler._runs
    assert session.cancel_token.is_cancelled()
    assert scheduler.off_lock_runner._thread.name == FLEET_OFF_LOCK_THREAD_NAME


# --- shared -------------------------------------------------------------------


def test_both_schedulers_are_table_stream_schedulers(make_fleet_table_stream_scheduler) -> None:
    assert isinstance(InferenceRowScheduler(), TableStreamScheduler)
    assert isinstance(make_fleet_table_stream_scheduler(), TableStreamScheduler)


def test_no_collection_runs_while_a_registry_holds_its_lock() -> None:
    registry: TableStreamRegistry[str, object] = TableStreamRegistry()
    seen_locked: list[bool] = []

    class _Probe:
        def __init__(self) -> None:
            self.cycle = self

        def __del__(self) -> None:
            seen_locked.append(registry._lock.locked())

    controller = type("Controller", (), {"stream_token": "t"})()
    threshold = gc.get_threshold()
    gc.set_threshold(1)
    try:
        for _ in range(2000):
            _Probe()
            registry.attach("scope", controller)
            registry.detach("t", token_getter=lambda c: c.stream_token)
    finally:
        gc.set_threshold(*threshold)
        gc.collect()

    assert seen_locked
    assert not any(seen_locked)

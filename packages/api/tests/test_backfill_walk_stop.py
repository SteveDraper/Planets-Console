"""A stop ends every accepted Backfill earlier turns walk in one game.

``stop_backfill_walks`` settles the game's on-walk fleet and scoreboard nodes in
every perspective and returns its follow-up, which the caller runs after it:
the drain of what the stop queued, then a reschedule of each live row whose own
root the stop stopped. A hop no worker has picked is
aborted, and a queued fleet hop is dropped at its pick. A picked fleet step
finishes and persists, and its node then starts or requeues no further step
unless something still needs it. A running scoreboard solve aborts, so its
stamped run is cancelled and nothing persists. Everything else in the game, and
every other game, is left alone.

Most tests run a walk on an orchestrator whose pool has no workers (``Walk``),
so each test picks and finishes steps itself. The stamping tests run a whole
walk on the process orchestrator, held just before its baseline hop's ledger
write.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from api.analytics.fleet.compute_orchestration import (
    FLEET_FINALIZATION_LEG,
    FleetPersistencePolicy,
    scores_evidence_recovery,
)
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet_walk_analytics import FLEET_WALK_ANALYTIC_IDS
from api.analytics.military_score_inference.inference_row_runner import (
    TierJobContinue,
)
from api.analytics.scores.tier_row_run_registry import get_persist_admission, get_row_run
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.errors import ComputeScopeAbortedError
from api.compute.in_flight_settle import PlayerWork
from api.compute.orchestrator import ComputeHandle, ComputeOrchestrator, ComputeRequest
from api.compute.orchestrator_observers import StepItemIgnoredReason
from api.compute.orchestrator_state import ComputeNodeRun
from api.compute.running_step import RunningStepDisposition
from api.compute.runtime import get_compute_orchestrator, reset_orchestrators_for_tests
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.compute.wire import StepOutcome, StepResult
from api.exceptions import FleetScoresEvidenceOpenError
from api.services.backfill_walk_stop import stop_backfill_walks
from api.services.evidence_bump import BumpSettlePolicy
from api.streaming.table_stream.registry_catalog import live_table_streams
from api.streaming.table_stream.row_run_admission import PersistAdmission

from tests.compute_lifecycle_records import LifecycleRecord, record_lifecycle
from tests.off_mode_catch_up_helpers import FLEET_SCORES_REGISTRY, context_at_turn
from tests.on_walk_helpers import fleet_persistence
from tests.scores_exports_helpers import first_player_id
from tests.scores_ladder_helpers import durable_row_complete
from tests.walk_band_helpers import (
    BASELINE_WALK_TURNS,
    SHELL_TURN,
    WALK_GENERATION,
    WALK_TIMEOUT_SECONDS,
    BaselineWalk,
    Walk,
    end_shell,
    no_live_streams,
    start_walk_held_at_the_baseline_persist,
)
from tests.walk_stop_helpers import (
    WALK_ANALYTIC_IDS,
    assert_aborted,
    begin_pick,
    finish_step,
    non_terminal_walk_scopes,
    pick_baseline_hop,
    plant_node,
    take_queued_item,
    walk_node,
)

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")


@pytest.fixture(autouse=True)
def _no_live_streams() -> Iterator[None]:
    yield from no_live_streams()


@pytest.fixture
def walk(sample_turn) -> Walk:
    return Walk.at_shell_turn(sample_turn)


def _stop(orchestrator: ComputeOrchestrator, game_id: int) -> None:
    """Stop the game's walks, then run the follow-up the stop returns, as the route's task does."""
    follow_up = stop_backfill_walks(orchestrator, game_id)
    follow_up()


def _assert_dropped_by_the_start_gate(
    dropped: list[LifecycleRecord], running_step: RunningStepDisposition
) -> None:
    (record,) = dropped
    assert record.detail["reason"] == StepItemIgnoredReason.START_REFUSED
    assert record.detail["runningStep"] == running_step.name.lower()


# --- T1: unstarted hops abort; a queued hop drops at its pick; game H is untouched ---


def test_a_stop_aborts_unstarted_hops_in_every_perspective_and_drops_queued_ones_at_the_pick(
    walk,
):
    walk.submit_shell()
    other_perspective = plant_node(walk, perspective_offset=1, on_walk=True)
    other_game = plant_node(walk, game_offset=1, on_walk=True)
    dropped = record_lifecycle(walk.orchestrator, ("pool_item_dropped",))

    _stop(walk.orchestrator, walk.ctx.game_id)

    for turn in (4, 5, SHELL_TURN):
        assert_aborted(walk_node(walk, turn))
    assert_aborted(walk.orchestrator.nodes[other_perspective])
    queued = walk_node(walk, 3)
    assert queued.state == "running"
    assert queued.running_step is RunningStepDisposition.END_AFTER_STEP
    assert walk.orchestrator.nodes[other_game].state == "parked"

    assert not begin_pick(walk, take_queued_item(walk))

    assert_aborted(queued)
    _assert_dropped_by_the_start_gate(dropped, RunningStepDisposition.END_AFTER_STEP)
    assert non_terminal_walk_scopes(walk.orchestrator, walk.ctx.game_id) == set()


def test_a_bump_aborts_a_queued_step_and_its_pick_drops_it_as_not_running(walk):
    """The bump aborts the queued hop at its settle, so the pick finds no running node."""
    walk.submit_shell()

    walk.orchestrator.settle_in_flight_work(
        PlayerWork(
            game_id=walk.ctx.game_id,
            perspective=walk.ctx.perspective,
            player_id=walk.player_id,
            analytic_ids=FLEET_WALK_ANALYTIC_IDS,
        ),
        BumpSettlePolicy(watched_turns=frozenset()),
    )
    walk.orchestrator.drain_post_lock_callbacks()
    queued = walk_node(walk, 3)
    assert_aborted(queued)
    dropped = record_lifecycle(walk.orchestrator, ("pool_item_dropped",))

    assert not begin_pick(walk, take_queued_item(walk))

    assert_aborted(queued)
    (record,) = dropped
    assert record.detail["reason"] == StepItemIgnoredReason.NODE_NOT_RUNNING


# --- T2: a picked fleet step ends at its next start or requeue, and submits nothing ---


@dataclass(frozen=True)
class _StepEnding:
    """What the picked step returns, and anything that happens before it returns."""

    result_wire: Callable[[Walk], object]
    before_finish: Callable[[Walk, pytest.MonkeyPatch], None] = lambda _walk, _monkeypatch: None


def _bump_player_epoch(walk: Walk, _monkeypatch: pytest.MonkeyPatch) -> None:
    fleet_persistence(walk.ctx).invalidate_player_ledgers_from_turn(
        walk.ctx.game_id, walk.ctx.perspective, 3, walk.player_id, durable=True
    )


def _defer_the_persist_on_scores(walk: Walk, monkeypatch: pytest.MonkeyPatch) -> None:
    """The finalization persist's refusal while same-turn scores evidence is open."""

    def defer(_policy, _ctx, scope, _result_wire):
        raise FleetScoresEvidenceOpenError(
            "scores evidence open", recovery=scores_evidence_recovery(scope)
        )

    monkeypatch.setattr(FleetPersistencePolicy, "persist", defer)


def _outcome(outcome: StepOutcome) -> Callable[[Walk], object]:
    return lambda _walk: StepResult(outcome=outcome, payload={})


_ENDINGS = {
    "continue": _StepEnding(_outcome("continue")),
    "park": _StepEnding(_outcome("park")),
    "soft-defer": _StepEnding(_outcome("waiting_deps")),
    "recovery-outcome": _StepEnding(
        lambda walk: StepResult(
            outcome="waiting_deps", wait_recovery=scores_evidence_recovery(walk.scope(3))
        )
    ),
    "persist-defer": _StepEnding(_outcome("persist"), before_finish=_defer_the_persist_on_scores),
    "epoch-retry": _StepEnding(_outcome("complete"), before_finish=_bump_player_epoch),
}


@pytest.mark.parametrize("ending", _ENDINGS.values(), ids=_ENDINGS.keys())
def test_a_picked_fleet_step_ends_at_its_next_start_or_requeue_and_submits_nothing(
    walk, ending, monkeypatch
):
    item = pick_baseline_hop(walk)
    restarts = record_lifecycle(walk.orchestrator, ("epoch_retry", "persist_deferred"))
    _stop(walk.orchestrator, walk.ctx.game_id)
    ending.before_finish(walk, monkeypatch)
    nodes_before = set(walk.orchestrator.nodes)

    finish_step(walk, item, ending.result_wire(walk))

    assert_aborted(walk_node(walk, 3))
    assert set(walk.orchestrator.nodes) == nodes_before
    assert walk.pool.snapshot_work_queue() == ()
    assert restarts == []
    assert walk.orchestrator.metrics.epoch_discards == 0


def test_a_picked_fleet_step_completes_under_the_stop(walk):
    item = pick_baseline_hop(walk)
    _stop(walk.orchestrator, walk.ctx.game_id)

    finish_step(walk, item, StepResult(outcome="complete", payload={}))

    assert walk_node(walk, 3).state == "complete"


def test_a_needed_fleet_node_continues_and_the_start_gate_re_derives_needed(walk):
    item = pick_baseline_hop(walk)
    dependent = plant_node(
        walk,
        analytic_id=SCORES_ANALYTIC_ID,
        turn=3,
        on_walk=False,
        dependency_scopes=(walk.scope(3),),
    )
    unregister_hold = walk.orchestrator.observers.register_dispatch_gate(lambda walk_node: False)
    _stop(walk.orchestrator, walk.ctx.game_id)

    finish_step(walk, item, StepResult(outcome="continue"))

    hop = walk_node(walk, 3)
    assert hop.state == "ready"
    assert hop.running_step is RunningStepDisposition.END_AFTER_STEP

    walk.orchestrator.abort_scope(dependent, ComputeScopeAbortedError("dependent ended"))
    unregister_hold()
    walk.dispatch_pass()

    assert_aborted(hop)


def test_an_inline_step_whose_node_stops_being_needed_during_its_wire_build_does_not_run(
    walk, monkeypatch
):
    item = pick_baseline_hop(walk)
    dependent = plant_node(
        walk,
        analytic_id=SCORES_ANALYTIC_ID,
        turn=3,
        on_walk=False,
        dependency_scopes=(walk.scope(3),),
    )
    unregister_hold = walk.orchestrator.observers.register_dispatch_gate(lambda walk_node: False)
    _stop(walk.orchestrator, walk.ctx.game_id)
    finish_step(walk, item, StepResult(outcome="continue"))
    fleet = FLEET_SCORES_REGISTRY[FLEET_ANALYTIC_ID]
    finalized: list[object] = []

    def build_while_the_dependent_ends(_scope, **_kwargs) -> dict:
        walk.orchestrator.abort_scope(dependent, ComputeScopeAbortedError("dependent ended"))
        return {}

    monkeypatch.setitem(
        fleet.build_step_job_wire, FLEET_FINALIZATION_LEG, build_while_the_dependent_ends
    )
    monkeypatch.setitem(fleet.run_step, FLEET_FINALIZATION_LEG, finalized.append)
    unregister_hold()
    walk.dispatch_pass()

    assert finalized == []
    assert_aborted(walk_node(walk, 3))


# --- T3: a running scoreboard tier aborts end to end ---


def test_a_running_scoreboard_tier_aborts_its_stamped_run_and_persists_nothing(ladder, monkeypatch):
    delivered: list[dict[str, object]] = []
    monkeypatch.setattr(
        ladder.scheduler, "_deliver_row_terminal", lambda **kwargs: delivered.append(kwargs)
    )
    ladder.orchestrator.observers.register_scope_outcome_listener(
        ladder.scheduler._on_orchestrator_scope_outcome
    )
    ladder.submit(
        submission_open=SubmissionOpen(
            open_turn=ladder.scope.turn + 1, backfill_earlier_turns=True, on_walk=True
        )
    )
    ladder.run_tier(TierJobContinue())
    stamped = ladder.session
    work = ladder.submitted_work[-1]
    job_wire = work.job_wire_for(ladder.scope)
    generation = ladder.orchestrator.nodes[ladder.scope].execution_generation

    _stop(ladder.orchestrator, ladder.ctx.game_id)

    node = ladder.orchestrator.nodes[ladder.scope]
    assert node.state == "failed"
    assert isinstance(node.error, ComputeScopeAbortedError)
    assert stamped.cancel_token.is_cancelled()
    assert get_persist_admission(stamped.run_id) is PersistAdmission.CANCEL_DENY
    assert get_row_run(stamped.run_id) is None

    monkeypatch.setattr(
        "api.analytics.scores.compute_orchestration.run_inference_tier_job",
        lambda *_args, **_kwargs: durable_row_complete("after the stop"),
    )
    ladder.orchestrator.complete_pool_step(
        ladder.scope, generation, result_wire=work.run_step(job_wire)
    )

    assert ladder.persisted_summary() is None
    assert delivered == []


# --- T5 and T6: a picked fleet step stamps, unless a bump moved the mark ---


@pytest.fixture
def held_walk(sample_turn) -> Iterator[BaselineWalk]:
    reset_orchestrators_for_tests()
    walk = start_walk_held_at_the_baseline_persist(sample_turn, before_write=True)
    yield walk
    walk.release_baseline_hop.set()
    reset_orchestrators_for_tests()


def _wait_ended(handle: ComputeHandle) -> BaseException:
    with pytest.raises(ComputeScopeAbortedError) as raised:
        handle.wait(timeout=WALK_TIMEOUT_SECONDS)
    return raised.value


def _baseline_hop_node(walk: BaselineWalk) -> ComputeNodeRun:
    return get_compute_orchestrator().nodes[walk.baseline_hop()]


def _wait_terminal(node: ComputeNodeRun) -> None:
    handle = ComputeHandle(
        scope=node.scope, _node=node, _condition=get_compute_orchestrator()._condition
    )
    handle.wait(timeout=WALK_TIMEOUT_SECONDS)


def _walk_keys(walk: BaselineWalk) -> tuple[int, int, int]:
    return walk.ctx.game_id, walk.ctx.perspective, walk.player_id


def test_a_picked_fleet_step_stamps_the_walk_generation_then_its_node_ends(held_walk):
    orchestrator = get_compute_orchestrator()
    _stop(orchestrator, held_walk.ctx.game_id)
    hop = _baseline_hop_node(held_walk)
    assert hop.running_step is RunningStepDisposition.END_AFTER_STEP

    held_walk.release_baseline_hop.set()
    _wait_ended(held_walk.handle)
    with pytest.raises(ComputeScopeAbortedError):
        _wait_terminal(hop)

    persistence = fleet_persistence(held_walk.ctx)
    game_id, perspective, player_id = _walk_keys(held_walk)
    baseline_turn, *later_turns = BASELINE_WALK_TURNS
    ledger = persistence.get_ledger(game_id, perspective, baseline_turn, player_id)
    assert ledger is not None
    assert ledger.evidence_generation == WALK_GENERATION
    assert persistence.evidence_mark(game_id, perspective, player_id).evidence_generation == (
        WALK_GENERATION
    )
    assert persistence.player_invalidation_generation(game_id, perspective, player_id) == 0
    for turn in later_turns:
        assert persistence.get_ledger(game_id, perspective, turn, player_id) is None
    assert non_terminal_walk_scopes(orchestrator, game_id) == set()
    assert not any(scope.analytic_id == SCORES_ANALYTIC_ID for scope in orchestrator.nodes)


def test_after_a_bump_the_picked_fleet_persist_is_refused_and_its_node_ends(held_walk):
    orchestrator = get_compute_orchestrator()
    epoch_retries = record_lifecycle(orchestrator, ("epoch_retry",))
    _stop(orchestrator, held_walk.ctx.game_id)
    game_id, perspective, player_id = _walk_keys(held_walk)
    persistence = fleet_persistence(held_walk.ctx)
    baseline_turn = BASELINE_WALK_TURNS[0]
    persistence.invalidate_player_ledgers_from_turn(
        game_id, perspective, baseline_turn, player_id, durable=True
    )
    hop = _baseline_hop_node(held_walk)

    held_walk.release_baseline_hop.set()
    with pytest.raises(ComputeScopeAbortedError):
        _wait_terminal(hop)

    assert persistence.get_ledger(game_id, perspective, baseline_turn, player_id) is None
    assert epoch_retries == []
    assert non_terminal_walk_scopes(orchestrator, game_id) == set()


# --- T7: other work runs on; a needed node finishes; a non-shell on-walk caller is stopped ---


def test_work_off_the_walk_and_in_other_analytics_runs_on(walk):
    walk.submit_shell()
    off_walk = plant_node(walk, turn=SHELL_TURN + 1, on_walk=False)
    off_walk_running = plant_node(walk, turn=SHELL_TURN + 2, on_walk=False, state="running")
    other_analytic = plant_node(walk, analytic_id="territory", on_walk=True)

    # The settle alone: this orchestrator's registry has no territory analytic to dispatch.
    stop_backfill_walks(walk.orchestrator, walk.ctx.game_id)

    assert walk.orchestrator.nodes[off_walk].state == "parked"
    assert walk.orchestrator.nodes[off_walk_running].state == "running"
    assert walk.orchestrator.nodes[off_walk_running].running_step is RunningStepDisposition.CONTINUE
    assert walk.orchestrator.nodes[other_analytic].state == "parked"


def test_a_needed_walk_node_runs_to_completion_and_stamps(held_walk):
    orchestrator = get_compute_orchestrator()
    game_id, perspective, player_id = _walk_keys(held_walk)
    baseline_turn = BASELINE_WALK_TURNS[0]
    dependent = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=game_id,
        perspective=perspective,
        turn=baseline_turn + 1,
        player_id=player_id,
    )
    with orchestrator._condition:
        orchestrator.nodes[dependent] = ComputeNodeRun(
            scope=dependent,
            dependency_scopes=(held_walk.baseline_hop(),),
            state="parked",
            submission_open=SubmissionOpen(),
        )
    _stop(orchestrator, game_id)
    hop = _baseline_hop_node(held_walk)

    held_walk.release_baseline_hop.set()
    _wait_terminal(hop)

    assert hop.state == "complete"
    persistence = fleet_persistence(held_walk.ctx)
    assert persistence.has_final_ledger(game_id, perspective, baseline_turn, player_id)
    ledger = persistence.get_ledger(game_id, perspective, baseline_turn, player_id)
    assert ledger is not None
    assert ledger.evidence_generation == WALK_GENERATION
    assert persistence.player_invalidation_generation(game_id, perspective, player_id) == 0
    scores_rows = held_walk.ctx.export_services[SCORES_ANALYTIC_ID].persistence
    assert scores_rows.get_row(game_id, perspective, baseline_turn, player_id) is not None
    assert orchestrator.nodes[dependent].state == "parked"


def test_an_on_walk_ensure_from_another_caller_is_stopped_and_its_waiter_sees_the_abort(walk):
    """An export-style ensure in a backfill-on game is on the walk (ledger D15)."""
    handle = walk.orchestrator.submit(
        ComputeRequest(
            scope=walk.scope(SHELL_TURN), ctx=walk.ctx, priority_band="interactive_ensure"
        )
    )
    assert walk_node(walk, SHELL_TURN).submission_open.on_walk

    _stop(walk.orchestrator, walk.ctx.game_id)

    _wait_ended(handle)


# --- T8: a reopen replaces failed scopes and joins a running fleet node ---


def test_a_reopen_replaces_the_stopped_walks_failed_scopes(walk):
    walk.submit_shell()
    stopped = {turn: walk_node(walk, turn).execution_generation for turn in (3, 4, 5, SHELL_TURN)}
    _stop(walk.orchestrator, walk.ctx.game_id)
    assert not begin_pick(walk, take_queued_item(walk))

    walk.submit_shell()

    for turn, generation in stopped.items():
        node = walk_node(walk, turn)
        assert not node.is_terminal
        assert node.execution_generation > generation
        assert node.running_step is RunningStepDisposition.CONTINUE


def test_a_reopen_joins_a_running_fleet_node_through_its_planned_dependent(walk):
    item = pick_baseline_hop(walk)
    _stop(walk.orchestrator, walk.ctx.game_id)
    hop = walk_node(walk, 3)
    unregister_hold = walk.orchestrator.observers.register_dispatch_gate(lambda walk_node: False)

    walk.submit_shell()

    assert walk_node(walk, 3) is hop
    assert hop.running_step is RunningStepDisposition.END_AFTER_STEP
    finish_step(walk, item, StepResult(outcome="continue"))
    assert hop.state == "ready"
    unregister_hold()


def test_a_root_attach_lowers_end_after_step(walk):
    item = pick_baseline_hop(walk)
    _stop(walk.orchestrator, walk.ctx.game_id)
    hop = walk_node(walk, 3)

    walk.submit_shell(3)

    assert walk_node(walk, 3) is hop
    assert hop.running_step is RunningStepDisposition.CONTINUE
    assert begin_pick(walk, item)


# --- T9: a game with no walk ---


def test_a_stop_in_a_game_with_no_walk_changes_nothing_and_the_rows_detach(sample_turn):
    host, ctx = context_at_turn(sample_turn, SHELL_TURN + 2)
    walk = Walk(ctx, first_player_id(host))
    shell = walk.open_shell()
    walk.submit_shell()
    before = {
        scope: (node.state, node.execution_generation, node.running_step)
        for scope, node in walk.orchestrator.nodes.items()
    }
    assert before
    assert not any(node.submission_open.on_walk for node in walk.orchestrator.nodes.values())

    _stop(walk.orchestrator, walk.ctx.game_id)
    end_shell(shell)

    assert {
        scope: (node.state, node.execution_generation, node.running_step)
        for scope, node in walk.orchestrator.nodes.items()
    } == before
    assert live_table_streams(WALK_ANALYTIC_IDS) == ()


# --- Rows still open on the game: the follow-up reschedules those whose own root it stopped ---

_STOPPED_ROOT_CASES = {
    "unstarted fleet root on the walk aborts": (FLEET_ANALYTIC_ID, "parked", True, True),
    "running fleet root on the walk ends after its step": (
        FLEET_ANALYTIC_ID,
        "running",
        True,
        True,
    ),
    "running scoreboard root on the walk aborts": (SCORES_ANALYTIC_ID, "running", True, True),
    "unstarted fleet root off the walk is kept": (FLEET_ANALYTIC_ID, "parked", False, False),
    "running fleet root off the walk is kept": (FLEET_ANALYTIC_ID, "running", False, False),
}


@pytest.mark.parametrize(
    ("analytic_id", "state", "on_walk", "is_rescheduled"),
    _STOPPED_ROOT_CASES.values(),
    ids=_STOPPED_ROOT_CASES.keys(),
)
def test_the_follow_up_reschedules_a_live_row_whose_own_root_the_stop_stopped(
    walk, analytic_id, state, on_walk, is_rescheduled
):
    shell = walk.open_shell()
    plant_node(walk, analytic_id=analytic_id, state=state, on_walk=on_walk)
    row_stream, other_stream = (
        (shell.fleet_stream, shell.scores_stream)
        if analytic_id == FLEET_ANALYTIC_ID
        else (shell.scores_stream, shell.fleet_stream)
    )

    follow_up = stop_backfill_walks(walk.orchestrator, walk.ctx.game_id)
    assert row_stream.rescheduled_player_ids == []
    follow_up()

    assert row_stream.rescheduled_player_ids == ([walk.player_id] if is_rescheduled else [])
    assert other_stream.rescheduled_player_ids == []
    end_shell(shell)


def test_the_follow_up_reschedules_only_after_its_drain_ran_the_abort_listeners(walk, monkeypatch):
    shell = walk.open_shell()
    root = plant_node(walk, on_walk=True)
    order: list[tuple[str, object]] = []
    walk.orchestrator.observers.register_scope_outcome_listener(
        lambda snapshot: order.append(("outcome", snapshot.scope))
    )
    reschedule_player = shell.fleet_stream.reschedule_player

    def record_reschedule(player_id: int) -> bool:
        order.append(("reschedule", player_id))
        return reschedule_player(player_id)

    monkeypatch.setattr(shell.fleet_stream, "reschedule_player", record_reschedule)

    _stop(walk.orchestrator, walk.ctx.game_id)

    assert order == [("outcome", root), ("reschedule", walk.player_id)]
    end_shell(shell)


def test_a_row_closed_before_the_follow_up_runs_is_not_rescheduled(walk):
    shell = walk.open_shell()
    plant_node(walk, on_walk=True)

    follow_up = stop_backfill_walks(walk.orchestrator, walk.ctx.game_id)
    end_shell(shell)
    follow_up()

    assert shell.fleet_stream.rescheduled_player_ids == []

"""Compute diagnostic mode covers a stale recompute of fleet and scoreboard.

A recompute behind fleet evidence generation is ordinary orchestrator work under
freeze, single-step and the allowlist. These tests drive a player's Backfill
earlier turns walk (``Walk``: a worker-less pool, so each pick is the test's)
with compute diagnostics bound to its orchestrator and the walk's shell as the
operator shell.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from api.analytics.military_score_inference.inference_scheduler import get_inference_row_scheduler
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.compute.diagnostics import (
    ShellContextKey,
    get_compute_diagnostics_controller,
    reset_compute_diagnostics_for_tests,
    snapshot_to_wire,
)
from api.compute.diagnostics.controller import ComputeDiagnosticsController
from api.compute.orchestrator_state import ComputeNodeRun
from api.compute.pools import PoolWorkItem
from api.compute.running_step import RunningStepDisposition
from api.compute.wire import StepResult
from api.config import ApiConfig, set_config
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.compute_lifecycle_records import record_lifecycle
from tests.compute_pool_test_helpers import QUEUED_ONLY_STEP_WORK
from tests.off_mode_catch_up_helpers import context_at_turn, store_generation, write_evidence_mark
from tests.on_walk_helpers import fleet_persistence
from tests.scores_exports_helpers import first_player_id
from tests.walk_band_helpers import SHELL_TURN, WALK_TURNS, Walk, end_shell, no_live_streams
from tests.walk_stop_helpers import (
    assert_aborted,
    assert_dropped_by_the_start_gate,
    begin_pick,
    finish_step,
    plant_node,
    stop_walks_and_follow_up,
    take_queued_item,
    walk_node,
)

pytestmark = pytest.mark.usefixtures("no_scores_row_runs")

BASELINE_TURN = 3


@pytest.fixture(autouse=True)
def _diagnostics_enabled() -> Iterator[None]:
    reset_compute_diagnostics_for_tests()
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=True))
    yield from no_live_streams()
    reset_compute_diagnostics_for_tests()
    set_config(ApiConfig(storage_backend="ephemeral", compute_diagnostics=False))


@pytest.fixture
def walk(sample_turn) -> Walk:
    """The player's walk with Backfill earlier turns on, at the shell turn."""
    return Walk.at_shell_turn(sample_turn)


def _shell(walk: Walk, *, turn: int = SHELL_TURN, perspective_offset: int = 0) -> ShellContextKey:
    return ShellContextKey(
        game_id=walk.ctx.game_id, perspective=walk.ctx.perspective + perspective_offset, turn=turn
    )


def _diagnose(
    walk: Walk, *, turn: int = SHELL_TURN
) -> tuple[ComputeDiagnosticsController, ShellContextKey]:
    """Bind diagnostics to the walk's orchestrator and make ``turn`` the operator shell."""
    controller = get_compute_diagnostics_controller()
    controller.bind_orchestrator(walk.orchestrator)
    shell = _shell(walk, turn=turn)
    controller.on_shell_context(shell)
    return controller, shell


def _complete_hops_through(walk: Walk, last_turn: int) -> None:
    """Pick and finish the walk's hops from the baseline through ``last_turn``."""
    for turn in range(BASELINE_TURN, last_turn + 1):
        assert walk.pick()[0] == walk.scope(turn)
        walk.complete_picked(walk.scope(turn))


def _bump(walk: Walk, host_turn: int, *, backfill_enabled: bool = True) -> None:
    """A durable bump of the walk player's evidence at ``host_turn``."""
    InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=fleet_persistence(walk.ctx),
        orchestrator=lambda: walk.orchestrator,
    ).on_inference_evidence_updated(
        walk.ctx.game_id,
        walk.ctx.perspective,
        host_turn,
        walk.player_id,
        durable=True,
        backfill_earlier_turns=backfill_enabled,
    )
    walk.orchestrator.drain_post_lock_callbacks()


def _queued_items(controller: ComputeDiagnosticsController, shell: ShellContextKey) -> list:
    return snapshot_to_wire(controller.snapshot(shell))["poolQueue"]


# --- A bump drops the hops freeze is holding ---


def test_a_bump_aborts_the_ready_hop_the_dispatch_gate_holds(walk):
    controller, shell = _diagnose(walk)
    controller.set_freeze_armed(shell, freeze_armed=True)
    walk.submit_shell()
    hop = walk_node(walk, BASELINE_TURN)
    assert hop.state == "ready"
    assert _queued_items(controller, shell) == []

    _bump(walk, BASELINE_TURN + 1)

    assert_aborted(hop)
    assert walk.pool.take_next_item_for_tests() is None


def test_a_bump_drops_the_queued_hop_the_dequeue_hold_holds(walk):
    controller, shell = _diagnose(walk)
    walk.submit_shell()
    controller.set_freeze_armed(shell, freeze_armed=True)
    hop = walk_node(walk, BASELINE_TURN)
    assert hop.state == "running"
    assert len(_queued_items(controller, shell)) == 1
    assert walk.pool.take_next_item_for_tests() is None
    dropped = record_lifecycle(walk.orchestrator, ("pool_item_dropped",))

    _bump(walk, BASELINE_TURN + 1)
    assert_aborted(hop)
    (ended,) = _queued_items(controller, shell)
    assert ended["state"] == "queued"
    picked = walk.pool.take_next_item_for_tests()
    assert picked is not None and picked.item.scope == hop.scope
    walk.pool._execute_item(picked)

    assert [record.detail["reason"] for record in dropped] == ["node_not_running"]
    assert _queued_items(controller, shell) == []
    assert (
        fleet_persistence(walk.ctx).get_ledger(
            walk.ctx.game_id, walk.ctx.perspective, BASELINE_TURN, walk.player_id
        )
        is None
    )


def test_with_the_setting_off_a_held_off_walk_item_on_a_live_row_turn_is_kept(walk):
    controller, shell = _diagnose(walk)
    row = walk.open_shell(turn=BASELINE_TURN)
    kept_scope = plant_node(walk, turn=BASELINE_TURN, on_walk=False, state="running")
    kept: ComputeNodeRun = walk.orchestrator.nodes[kept_scope]
    walk.dispatch_pass()
    registration_id = walk.orchestrator.pool_registration_id
    assert registration_id is not None
    walk.pool.enqueue_for_tests(
        PoolWorkItem(
            orchestrator_id=registration_id,
            scope=kept_scope,
            execution_generation=kept.execution_generation,
            step_kind="materialize",
            backend="thread",
            step_index=0,
            work=QUEUED_ONLY_STEP_WORK,
        )
    )
    controller.set_freeze_armed(shell, freeze_armed=True)

    _bump(walk, SHELL_TURN, backfill_enabled=False)

    assert kept.state == "running"
    assert walk.pool.take_next_item_for_tests() is None
    assert len(_queued_items(controller, shell)) == 1
    end_shell(row)


# --- A walk stop leaves the queued hop freeze is holding running, to end at its pick ---


def _stop_with_the_baseline_hop_held(
    walk: Walk,
) -> tuple[ComputeDiagnosticsController, ShellContextKey, ComputeNodeRun]:
    """Queue the baseline hop, arm freeze so the dequeue hold keeps it, then stop the walk."""
    controller, shell = _diagnose(walk)
    walk.submit_shell()
    controller.set_freeze_armed(shell, freeze_armed=True)
    hop = walk_node(walk, BASELINE_TURN)
    assert hop.state == "running"

    stop_walks_and_follow_up(walk.orchestrator, walk.ctx.game_id)

    return controller, shell, hop


def _disarm(controller: ComputeDiagnosticsController, shell: ShellContextKey, _walk: Walk) -> None:
    controller.set_freeze_armed(shell, freeze_armed=False)


def _single_step(
    controller: ComputeDiagnosticsController, shell: ShellContextKey, walk: Walk
) -> None:
    controller.set_allowlist(shell, frozenset({walk.player_id}))
    assert controller.single_step(shell) is True


@pytest.mark.parametrize("release", [_disarm, _single_step], ids=["disarm", "single_step"])
def test_a_walk_stop_leaves_the_held_hop_running_until_its_release_drops_it_at_its_pick(
    walk, release
):
    controller, shell, hop = _stop_with_the_baseline_hop_held(walk)
    dropped = record_lifecycle(walk.orchestrator, ("pool_item_dropped",))

    assert hop.state == "running"
    assert hop.running_step is RunningStepDisposition.END_AFTER_STEP
    assert len(_queued_items(controller, shell)) == 1
    assert walk.pool.take_next_item_for_tests() is None

    release(controller, shell, walk)
    assert not begin_pick(walk, take_queued_item(walk))

    assert_aborted(hop)
    assert_dropped_by_the_start_gate(dropped, RunningStepDisposition.END_AFTER_STEP)
    assert _queued_items(controller, shell) == []


def test_a_root_attach_after_a_walk_stop_lets_the_held_hop_run_after_disarm(walk):
    row = walk.open_shell(turn=BASELINE_TURN)
    controller, shell, hop = _stop_with_the_baseline_hop_held(walk)
    assert row.fleet_stream.rescheduled_player_ids == [walk.player_id]

    walk.submit_shell(BASELINE_TURN)

    assert walk_node(walk, BASELINE_TURN) is hop
    assert hop.running_step is RunningStepDisposition.CONTINUE
    assert walk.pool.take_next_item_for_tests() is None
    controller.set_freeze_armed(shell, freeze_armed=False)
    item = take_queued_item(walk)
    assert item.scope == hop.scope
    assert begin_pick(walk, item)
    finish_step(walk, item, StepResult(outcome="complete"))
    assert hop.state == "complete"
    end_shell(row)


# --- Work outside the operator shell's diagnostic scope keeps running ---


def test_a_perspective_change_releases_the_walk_left_behind(walk):
    controller, shell = _diagnose(walk)
    controller.set_freeze_armed(shell, freeze_armed=True)
    walk.submit_shell()
    assert walk_node(walk, BASELINE_TURN).state == "ready"
    assert walk.pool.take_next_item_for_tests() is None

    controller.on_shell_context(_shell(walk, perspective_offset=1))

    assert walk.pick()[0] == walk.scope(BASELINE_TURN)
    walk.complete_picked(walk.scope(BASELINE_TURN))
    assert walk.pick()[0] == walk.scope(BASELINE_TURN + 1)


def test_a_turn_change_below_the_walks_frontier_releases_it(walk):
    frontier = BASELINE_TURN + 2
    controller, shell = _diagnose(walk)
    walk.submit_shell()
    _complete_hops_through(walk, frontier - 2)
    assert walk.pick()[0] == walk.scope(frontier - 1)
    controller.set_freeze_armed(shell, freeze_armed=True)
    walk.complete_picked(walk.scope(frontier - 1))
    assert walk_node(walk, frontier).state == "ready"
    assert walk.pool.take_next_item_for_tests() is None

    controller.on_shell_context(_shell(walk, turn=frontier - 1))

    assert walk.pick()[0] == walk.scope(frontier)


def test_a_turn_change_at_or_above_the_walks_frontier_leaves_it_frozen(walk):
    controller, shell = _diagnose(walk)
    controller.set_freeze_armed(shell, freeze_armed=True)
    walk.submit_shell()

    controller.on_shell_context(_shell(walk, turn=BASELINE_TURN + 1))

    assert walk_node(walk, BASELINE_TURN).state == "ready"
    assert walk.pool.take_next_item_for_tests() is None


def test_a_hop_above_the_operator_shell_turn_runs_while_freeze_is_armed(walk):
    frontier = BASELINE_TURN + 2
    controller, shell = _diagnose(walk, turn=frontier - 1)
    walk.submit_shell()
    _complete_hops_through(walk, frontier - 2)
    assert walk.pick()[0] == walk.scope(frontier - 1)
    controller.set_freeze_armed(shell, freeze_armed=True)

    walk.complete_picked(walk.scope(frontier - 1))

    assert walk.pick()[0] == walk.scope(frontier)


# --- A stale recompute is ordinary work under freeze ---


def test_with_the_setting_on_the_walk_is_planned_and_held_ready(walk):
    controller, shell = _diagnose(walk)
    controller.set_freeze_armed(shell, freeze_armed=True)

    walk.submit_shell()

    assert {turn: walk_node(walk, turn).state for turn in WALK_TURNS} == {
        BASELINE_TURN: "ready",
        **dict.fromkeys(WALK_TURNS[1:], "waiting_deps"),
    }
    assert walk.pool.take_next_item_for_tests() is None
    assert (
        fleet_persistence(walk.ctx)
        .evidence_mark(walk.ctx.game_id, walk.ctx.perspective, walk.player_id)
        .applies_from_turn
        == BASELINE_TURN
    )


def test_with_the_setting_off_the_stale_open_catch_up_is_planned_and_held_ready(sample_turn):
    host, ctx = context_at_turn(sample_turn, SHELL_TURN + 2)
    off_mode = Walk(ctx, first_player_id(host))
    persistence = fleet_persistence(ctx)
    keys = (ctx.game_id, ctx.perspective)
    write_evidence_mark(
        persistence, *keys, off_mode.player_id, generation=2, applies_from=SHELL_TURN - 2
    )
    store_generation(persistence, *keys, SHELL_TURN - 2, off_mode.player_id, 2, ship_id=1)
    store_generation(persistence, *keys, SHELL_TURN - 1, off_mode.player_id, 1, ship_id=2)
    controller, shell = _diagnose(off_mode)
    controller.set_freeze_armed(shell, freeze_armed=True)

    off_mode.submit_shell()

    assert walk_node(off_mode, SHELL_TURN - 1).state == "ready"
    assert walk_node(off_mode, SHELL_TURN).state == "waiting_deps"
    assert off_mode.scope(SHELL_TURN - 2) not in off_mode.orchestrator.nodes
    assert off_mode.pool.take_next_item_for_tests() is None


def test_the_replacement_walk_after_a_bump_is_held_ready(walk):
    controller, shell = _diagnose(walk)
    controller.set_freeze_armed(shell, freeze_armed=True)
    walk.submit_shell()
    aborted_hop = walk_node(walk, BASELINE_TURN)

    _bump(walk, BASELINE_TURN + 1)
    walk.submit_shell()

    replacement_hop = walk_node(walk, BASELINE_TURN)
    assert replacement_hop is not aborted_hop
    assert replacement_hop.state == "ready"
    assert walk.pool.take_next_item_for_tests() is None


def test_arming_and_disarming_freeze_leaves_inference_global_pause_alone(walk):
    controller, shell = _diagnose(walk)
    scheduler = get_inference_row_scheduler()
    scores_scope = InferenceStreamScope(walk.ctx.game_id, walk.ctx.perspective, SHELL_TURN)
    before = scheduler.global_pause_status(scores_scope)

    controller.set_freeze_armed(shell, freeze_armed=True)
    while_frozen = scheduler.global_pause_status(scores_scope)
    controller.set_freeze_armed(shell, freeze_armed=False)

    assert before == while_frozen == scheduler.global_pause_status(scores_scope)


# --- Single-step releases one hop for a focused player ---


def test_single_step_releases_the_focused_players_frontier_hop_then_refreezes(walk):
    controller, shell = _diagnose(walk)
    controller.set_freeze_armed(shell, freeze_armed=True)
    controller.set_allowlist(shell, frozenset({walk.player_id}))
    walk.submit_shell()

    assert controller.single_step(shell) is True

    assert walk.pick()[0] == walk.scope(BASELINE_TURN)
    assert walk.pool.take_next_item_for_tests() is None
    walk.complete_picked(walk.scope(BASELINE_TURN))
    assert walk_node(walk, BASELINE_TURN + 1).state == "ready"
    assert walk.pool.take_next_item_for_tests() is None


def test_single_step_reports_nothing_released_when_another_gate_refuses_the_target(walk):
    controller, shell = _diagnose(walk)
    controller.set_freeze_armed(shell, freeze_armed=True)
    controller.set_allowlist(shell, frozenset({walk.player_id}))
    walk.submit_shell()
    walk.orchestrator.observers.register_dispatch_gate(lambda _node: False)

    assert controller.single_step(shell) is False

    assert walk_node(walk, BASELINE_TURN).state == "ready"
    assert walk.pool.take_next_item_for_tests() is None

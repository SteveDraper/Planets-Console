"""A durable fleet evidence bump restarts the player's live walks under either setting.

The bump runs through the production service (``on_inference_evidence_updated``
with ``durable=True``) on a walk whose pool has no workers (``Walk``), so each
test picks and finishes steps itself. The shell's streams are stand-ins that
record each reschedule; a reschedule is the replacement submit, which a test
makes itself where it matters.

- With the setting on, the bump keeps nothing: every node of the player's walk
  is aborted, and each live row at the evidence host turn or later, or whose
  own root was stopped, is rescheduled.
- With the setting off, a running off-walk node on a live-row turn is kept. A
  kept step still queued runs on its pre-bump epoch, takes an epoch retry and
  never stamps.
- A turn with no live row is never woken, and another player is untouched.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_rows import (
    CachedCompleteRowAdmission,
    ScheduleRowAdmission,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_controller import (
    InferenceTableStreamController,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator_observers import StepItemIgnoredReason
from api.compute.running_step import RunningStepDisposition
from api.compute.wire import StepResult
from api.services.backfill_walk_stop import stop_backfill_walks
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend
from api.streaming.table_stream.connect import AdmissionDispatch

from tests.compute_lifecycle_records import record_lifecycle
from tests.export_chain_test_fixtures import enable_backfill_earlier_turns
from tests.off_mode_catch_up_helpers import context_at_turn, write_evidence_mark
from tests.on_walk_helpers import fleet_persistence
from tests.scores_exports_helpers import first_player_id, inference_target_player_id
from tests.test_scores_row_awaits_walk import (
    HOST_TURN,
    MARK_GENERATION,
    PRIOR_TURN,
    put_ensure_final_prior,
    stored_complete_row,
)
from tests.walk_band_helpers import SHELL_TURN, Walk, end_shell, no_live_streams
from tests.walk_stop_helpers import (
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

BASELINE_TURN = 3


@pytest.fixture(autouse=True)
def _no_live_streams() -> Iterator[None]:
    yield from no_live_streams()


@pytest.fixture
def walk(sample_turn) -> Walk:
    """The player's walk with Backfill earlier turns on, at the shell turn."""
    return Walk.at_shell_turn(sample_turn)


def _bump(walk: Walk, host_turn: int, *, backfill_enabled: bool = True) -> set[int]:
    """A durable bump of the walk player's evidence at ``host_turn``."""
    return InferenceInvalidationService(
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


def _mark_generation(walk: Walk) -> int:
    keys = (walk.ctx.game_id, walk.ctx.perspective, walk.player_id)
    return fleet_persistence(walk.ctx).evidence_mark(*keys).evidence_generation


# --- T1 and T3: setting on, the whole walk aborts and a returning step changes nothing ---


def test_with_the_setting_on_the_bump_aborts_the_walk_and_reschedules_the_live_rows(walk):
    shell = walk.open_shell()
    item = pick_baseline_hop(walk)
    assert non_terminal_walk_scopes(walk.orchestrator, walk.ctx.game_id)
    ignored = record_lifecycle(walk.orchestrator, ("pool_finish_ignored",))
    persistence = fleet_persistence(walk.ctx)
    keys = (walk.ctx.game_id, walk.ctx.perspective, walk.player_id)
    mark_before = _mark_generation(walk)

    _bump(walk, BASELINE_TURN + 1)
    walk.orchestrator.drain_post_lock_callbacks()

    assert non_terminal_walk_scopes(walk.orchestrator, walk.ctx.game_id) == set()
    assert_aborted(walk_node(walk, BASELINE_TURN))
    assert_aborted(walk_node(walk, SHELL_TURN))
    assert shell.fleet_stream.rescheduled_player_ids == [walk.player_id]
    assert shell.scores_stream.rescheduled_player_ids == [walk.player_id]
    assert _mark_generation(walk) == mark_before + 1

    finish_step(walk, item, StepResult(outcome="persist", payload={}))

    assert persistence.get_ledger(*keys[:2], BASELINE_TURN, keys[2]) is None
    assert [record.detail["reason"] for record in ignored] == [
        StepItemIgnoredReason.NODE_NOT_RUNNING
    ]
    assert walk.orchestrator.metrics.epoch_discards == 0
    end_shell(shell)


def test_the_rescheduled_rows_walk_replaces_the_aborted_nodes(walk):
    shell = walk.open_shell()
    pick_baseline_hop(walk)
    aborted_root = walk_node(walk, SHELL_TURN)
    _bump(walk, BASELINE_TURN + 1)

    walk.submit_shell()

    replacement = walk_node(walk, SHELL_TURN)
    assert replacement is not aborted_root
    assert not replacement.is_terminal
    assert replacement.execution_generation > aborted_root.execution_generation
    assert non_terminal_walk_scopes(walk.orchestrator, walk.ctx.game_id)
    end_shell(shell)


# --- T4: rows before the host turn wake only when their own work was stopped ---


def test_a_live_row_below_the_host_turn_wakes_only_when_the_bump_stopped_its_own_root(walk):
    shell_row = walk.open_shell()
    stopped_row = walk.open_shell(turn=BASELINE_TURN)
    idle_row = walk.open_shell(turn=BASELINE_TURN - 1)
    pick_baseline_hop(walk)

    _bump(walk, BASELINE_TURN + 1)

    assert shell_row.fleet_stream.rescheduled_player_ids == [walk.player_id]
    assert stopped_row.fleet_stream.rescheduled_player_ids == [walk.player_id]
    assert idle_row.fleet_stream.rescheduled_player_ids == []
    assert idle_row.scores_stream.rescheduled_player_ids == []
    for shell in (shell_row, stopped_row, idle_row):
        end_shell(shell)


# --- T5 and T7: no live row, nothing wakes; a reopen replaces the aborted walk ---


def test_with_no_live_row_the_bump_aborts_the_walk_and_wakes_nothing(walk, monkeypatch):
    submits: list[object] = []
    walk.submit_shell()
    original_submit = walk.orchestrator.submit
    monkeypatch.setattr(
        walk.orchestrator, "submit", lambda request: submits.append(request) or None
    )

    _bump(walk, BASELINE_TURN + 1)

    assert submits == []
    assert non_terminal_walk_scopes(walk.orchestrator, walk.ctx.game_id) == set()
    monkeypatch.setattr(walk.orchestrator, "submit", original_submit)
    aborted_root = walk_node(walk, SHELL_TURN)

    walk.submit_shell()

    assert walk_node(walk, SHELL_TURN) is not aborted_root
    assert not walk_node(walk, SHELL_TURN).is_terminal


# --- T6: setting off ---


def test_with_the_setting_off_running_off_walk_work_on_a_live_row_turn_is_kept(walk):
    live_turn = BASELINE_TURN
    row = walk.open_shell(turn=live_turn)
    kept = plant_node(walk, turn=live_turn, on_walk=False, state="running")
    on_walk_running = plant_node(walk, turn=live_turn + 1, on_walk=True, state="running")
    off_screen_root = plant_node(walk, turn=live_turn - 1, on_walk=False, state="waiting_deps")
    other_row = walk.open_shell(turn=live_turn + 1)

    _bump(walk, SHELL_TURN, backfill_enabled=False)

    node = walk.orchestrator.nodes[kept]
    assert node.state == "running"
    assert node.running_step is RunningStepDisposition.CONTINUE
    assert row.fleet_stream.rescheduled_player_ids == []
    assert_aborted(walk.orchestrator.nodes[on_walk_running])
    assert other_row.fleet_stream.rescheduled_player_ids == [walk.player_id]
    assert_aborted(walk.orchestrator.nodes[off_screen_root])
    for shell in (row, other_row):
        end_shell(shell)


def test_with_the_setting_off_a_queued_off_walk_step_is_kept_epoch_retried_and_never_stamps(
    sample_turn,
):
    """The kept step was committed under the pre-bump epoch and not yet picked.

    It runs on that epoch, so its persist result is discarded for an epoch
    retry, and the node is queued again under the bumped epoch.
    """
    host, ctx = context_at_turn(sample_turn, SHELL_TURN + 2)
    off_mode = Walk(ctx, first_player_id(host))
    persistence = fleet_persistence(ctx)
    keys = (ctx.game_id, ctx.perspective, off_mode.player_id)
    row = off_mode.open_shell(turn=BASELINE_TURN)
    off_mode.submit_shell(turn=BASELINE_TURN)
    queued = walk_node(off_mode, BASELINE_TURN)
    assert not queued.submission_open.on_walk
    epoch_before = persistence.player_invalidation_generation(*keys)
    assert queued.generation_at_submit == epoch_before
    retries = record_lifecycle(off_mode.orchestrator, ("epoch_retry", "pool_item_dropped"))

    _bump(off_mode, SHELL_TURN, backfill_enabled=False)
    off_mode.orchestrator.drain_post_lock_callbacks()

    epoch_after = persistence.player_invalidation_generation(*keys)
    assert epoch_after == epoch_before + 1
    item = take_queued_item(off_mode)
    assert item.scope == queued.scope
    assert begin_pick(off_mode, item)
    finish_step(off_mode, item, StepResult(outcome="persist", payload={}))
    off_mode.orchestrator.drain_post_lock_callbacks()

    assert [(record.kind, record.detail["generationAtSubmit"]) for record in retries] == [
        ("epoch_retry", epoch_before)
    ]
    assert persistence.get_ledger(keys[0], keys[1], BASELINE_TURN, keys[2]) is None
    assert walk_node(off_mode, BASELINE_TURN) is queued
    assert queued.state == "running"
    assert queued.generation_at_submit == epoch_after
    assert take_queued_item(off_mode).scope == queued.scope
    end_shell(row)


def test_with_the_setting_on_running_off_walk_work_on_a_live_row_turn_is_aborted(walk):
    row = walk.open_shell(turn=BASELINE_TURN)
    running = plant_node(walk, turn=BASELINE_TURN, on_walk=False, state="running")

    _bump(walk, SHELL_TURN, backfill_enabled=True)

    assert_aborted(walk.orchestrator.nodes[running])
    assert row.fleet_stream.rescheduled_player_ids == [walk.player_id]
    end_shell(row)


# --- T8: another player ---


def test_another_players_walk_and_rows_are_untouched(walk):
    other_player_walk = Walk(walk.ctx, walk.player_id + 1)
    other_player_walk.orchestrator = walk.orchestrator
    other_shell = other_player_walk.open_shell()
    other_player_walk.submit_shell()
    other_root = walk_node(other_player_walk, SHELL_TURN)
    walk.submit_shell()

    _bump(walk, BASELINE_TURN + 1)

    assert not other_root.is_terminal
    assert other_shell.fleet_stream.rescheduled_player_ids == []
    assert other_shell.scores_stream.rescheduled_player_ids == []
    end_shell(other_shell)


# --- T9: a node a game stop left to end after its step is aborted by the bump ---


def test_a_fleet_step_a_stop_left_running_is_aborted_by_the_bump_and_never_stamps(walk):
    item = pick_baseline_hop(walk)
    stop_backfill_walks(walk.orchestrator, walk.ctx.game_id)()
    hop = walk_node(walk, BASELINE_TURN)
    assert hop.state == "running"
    assert hop.running_step is RunningStepDisposition.END_AFTER_STEP

    _bump(walk, BASELINE_TURN + 1)

    assert_aborted(hop)
    finish_step(walk, item, StepResult(outcome="persist", payload={}))
    keys = (walk.ctx.game_id, walk.ctx.perspective)
    assert fleet_persistence(walk.ctx).get_ledger(*keys, BASELINE_TURN, walk.player_id) is None


# --- A queued hop the bump aborted is dropped at its pick ---


def test_a_hop_queued_before_the_bump_is_dropped_at_its_pick(walk):
    walk.submit_shell()
    queued = walk_node(walk, BASELINE_TURN)

    _bump(walk, BASELINE_TURN + 1)

    assert_aborted(queued)
    assert not begin_pick(walk, take_queued_item(walk))
    assert not any(
        scope.analytic_id == SCORES_ANALYTIC_ID and not node.is_terminal
        for scope, node in walk.orchestrator.nodes.items()
    )
    assert all(
        node.is_terminal
        for scope, node in walk.orchestrator.nodes.items()
        if scope.analytic_id == FLEET_ANALYTIC_ID and scope.player_id == walk.player_id
    )


# --- With the setting on, a scoreboard-only row with a stored row submits its walk ---


def test_with_the_setting_on_a_bumped_scoreboard_only_row_schedules_instead_of_its_stored_row(
    sample_turn, monkeypatch
):
    """The bump at the prior turn leaves that prior behind the new mark.

    The row's stored row was solved from the old prior, so its admission
    schedules, which submits the walk, instead of painting the stored row.
    """
    host, ctx = context_at_turn(sample_turn, HOST_TURN)
    enable_backfill_earlier_turns(ctx)
    player_id = inference_target_player_id(host)
    fleet = fleet_persistence(ctx)
    write_evidence_mark(
        fleet,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=MARK_GENERATION,
        applies_from=PRIOR_TURN,
    )
    put_ensure_final_prior(ctx, player_id, generation=MARK_GENERATION)
    rows = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    rows.put_row_without_notify(
        ctx.game_id, ctx.perspective, HOST_TURN, player_id, stored_complete_row()
    )
    scheduler = InferenceRowScheduler(worker_count=0)
    scope = InferenceStreamScope(ctx.game_id, ctx.perspective, HOST_TURN)
    controller = InferenceTableStreamController(
        scope=scope,
        stream_token=scheduler.begin_scope(scope),
        turn=host,
        player_ids=(player_id,),
        scheduler=scheduler,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        query_context=ctx,
        persistence=rows,
    )
    controller.attach()
    assert isinstance(controller.resolve_row_admission(player_id), CachedCompleteRowAdmission)
    admissions: list[object] = []
    monkeypatch.setattr(
        controller,
        "dispatch_admission",
        lambda _player_id, admission: (
            admissions.append(admission) or AdmissionDispatch(schedule_failed=True)
        ),
    )

    InferenceInvalidationService(rows, fleet_persistence=fleet).on_inference_evidence_updated(
        ctx.game_id, ctx.perspective, PRIOR_TURN, player_id, durable=True
    )

    assert [type(admission) for admission in admissions] == [ScheduleRowAdmission]
    controller.detach()


# --- The wake runs after the settle's abort listeners, and even when the mark write fails ---


def test_the_bump_drains_the_abort_listeners_before_it_reschedules_a_row(walk, monkeypatch):
    shell = walk.open_shell()
    walk.submit_shell()
    order: list[str] = []
    walk.orchestrator.observers.register_scope_outcome_listener(
        lambda snapshot: order.append("outcome") if snapshot.is_intentional_abort else None
    )
    reschedule_player = shell.fleet_stream.reschedule_player
    monkeypatch.setattr(
        shell.fleet_stream,
        "reschedule_player",
        lambda player_id: order.append("reschedule") or reschedule_player(player_id),
    )

    _bump(walk, BASELINE_TURN + 1)

    assert "reschedule" in order
    assert order.index("reschedule") > max(
        index for index, kind in enumerate(order) if kind == "outcome"
    )
    end_shell(shell)


@pytest.mark.allows_contained_callback_errors
def test_a_failed_mark_write_still_reschedules_the_rows_the_settle_stopped(walk, monkeypatch):
    shell = walk.open_shell()
    walk.submit_shell()

    def fail_the_mark_write(*_args, **_kwargs):
        raise OSError("mark write failed")

    monkeypatch.setattr(
        fleet_persistence(walk.ctx), "invalidate_player_ledgers_from_turn", fail_the_mark_write
    )

    with pytest.raises(OSError, match="mark write failed"):
        _bump(walk, BASELINE_TURN + 1)

    assert_aborted(walk_node(walk, SHELL_TURN))
    assert shell.fleet_stream.rescheduled_player_ids == [walk.player_id]
    end_shell(shell)


def test_an_interrupt_in_the_mark_write_propagates_without_the_wake(walk, monkeypatch):
    shell = walk.open_shell()
    walk.submit_shell()

    def interrupt_the_mark_write(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        fleet_persistence(walk.ctx), "invalidate_player_ledgers_from_turn", interrupt_the_mark_write
    )

    with pytest.raises(KeyboardInterrupt):
        _bump(walk, BASELINE_TURN + 1)

    assert_aborted(walk_node(walk, SHELL_TURN))
    assert shell.fleet_stream.rescheduled_player_ids == []
    end_shell(shell)

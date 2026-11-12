"""A walk's band follows the live shell streams that watch it.

Most tests plan a real fleet or scoreboard walk on an orchestrator whose pool
has no workers, so queued steps wait until the test picks them. The T1 tests
instead run a whole walk on the process orchestrator and pool, with real steps
and persists. ``tests.walk_band_helpers`` holds both harnesses.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator

import pytest
from api.analytics.fleet.fleet_table_stream_registry import (
    detach_fleet_table_stream,
    get_fleet_table_stream_registry,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.military_score_inference.inference_stream_domain_events import RowComplete
from api.analytics.military_score_inference.inference_table_stream_registry import (
    detach_inference_table_stream,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute import build_compute_registry
from api.compute.errors import ComputeScopeAbortedError
from api.compute.orchestrator import ComputeOrchestrator, ComputeRequest
from api.compute.persistence import PersistDependencyRecovery
from api.compute.priority_band import ComputeRequestBand
from api.compute.scope import ComputeScope
from api.streaming.table_stream.registry import TableStreamRegistry
from api.streaming.table_stream.registry_bootstrap import (
    ensure_table_stream_registries_registered,
)
from api.streaming.table_stream.registry_catalog import (
    register_table_stream_registry,
    reset_table_stream_registry_catalog_for_tests,
)
from api.streaming.table_stream.scoped_connect import iter_table_stream_connect_with_scope

from tests.fixtures.export_framework.harness import make_fixture_query_context
from tests.on_walk_live_helpers import LiveStream, attach_stream
from tests.test_compute_pool_published_bands import _player_scopes
from tests.test_compute_pools import _POOL_EXPORT_REGISTRY, _single_step_thread_registration
from tests.walk_band_helpers import (
    SHELL_TURN,
    WALK_TURNS,
    Walk,
    all_at,
    assert_walk_stamped_the_ensure_baseline_without_bumping,
    end_shell,
    finish_walk,
    no_live_streams,
    no_scores_row_runs,
    start_walk_held_at_the_baseline_persist,
)


@pytest.fixture(autouse=True)
def _no_live_streams() -> Iterator[None]:
    yield from no_live_streams()


@pytest.fixture
def walk(sample_turn) -> Walk:
    return Walk.at_shell_turn(sample_turn)


@pytest.fixture
def _no_scores_row_runs() -> Iterator[None]:
    yield from no_scores_row_runs()


class _HeldOpenFleetStreamPolicy:
    """Connect policy whose stream stays open on its preamble until the generator closes."""

    def __init__(self, scope: FleetTableStreamScope, controller: LiveStream) -> None:
        self.scope = scope
        self.controller = controller

    def attach(self) -> None:
        get_fleet_table_stream_registry().attach(self.scope, self.controller)

    def detach(self) -> None:
        detach_fleet_table_stream(self.controller.stream_token)

    def preamble_events(self) -> tuple[dict[str, object], ...]:
        return ({"type": "preamble"},)

    def end_sessions(self) -> None:
        pass


def _connect_fleet_stream(walk: Walk) -> Iterator[dict[str, object]]:
    """Open a fleet stream through the scoped connect entry and hold it open."""
    scope = FleetTableStreamScope(walk.ctx.game_id, walk.ctx.perspective, SHELL_TURN)
    controller = LiveStream(scope, None, walk.ctx, [walk.player_id])
    stream = iter_table_stream_connect_with_scope(
        begin_scope=lambda: controller.stream_token,
        end_scope=lambda _token: None,
        policy_factory=lambda _token: _HeldOpenFleetStreamPolicy(scope, controller),
        player_ids=(),
    )
    assert next(stream) == {"type": "preamble"}
    return stream


# --- T1: a walk reaches the ensure baseline whether its streams close or stay open ---


@pytest.mark.usefixtures("_no_scores_row_runs")
def test_closing_both_streams_mid_walk_still_reaches_the_ensure_baseline(sample_turn):
    walk = start_walk_held_at_the_baseline_persist(sample_turn)

    end_shell(walk.shell)
    finish_walk(walk)

    assert_walk_stamped_the_ensure_baseline_without_bumping(walk)


@pytest.mark.usefixtures("_no_scores_row_runs")
def test_a_walk_with_both_streams_open_reaches_the_ensure_baseline(sample_turn, caplog):
    walk = start_walk_held_at_the_baseline_persist(sample_turn)

    with caplog.at_level(logging.ERROR):
        finish_walk(walk)

    assert_walk_stamped_the_ensure_baseline_without_bumping(walk)
    assert [record for record in caplog.records if record.levelno >= logging.ERROR] == []
    assert walk.shell.fleet_stream.rescheduled_player_ids == []
    assert walk.shell.scores_stream.rescheduled_player_ids == [walk.player_id]
    [(delivered_player_id, delivered_event)] = walk.shell.scores_stream.delivered_events
    assert delivered_player_id == walk.player_id
    assert isinstance(delivered_event, RowComplete)


# --- T2: closing both streams drops unpicked steps to background ---


def test_closing_both_streams_drops_unpicked_steps_and_later_hops_to_background(walk):
    fleet_stream = walk.open_fleet_stream()
    scores_stream = walk.open_scores_stream()
    walk.submit_shell()
    assert walk.bands() == all_at("stream_attached")
    picked_before_close = walk.pick()
    assert picked_before_close == (walk.scope(3), "stream_attached")

    detach_fleet_table_stream(fleet_stream.stream_token)
    detach_inference_table_stream(scores_stream.stream_token)
    walk.complete_picked(walk.scope(3))

    assert walk.bands((4, 5, 6)) == all_at("background", (4, 5, 6))
    assert walk.pick() == (walk.scope(4), "background")
    walk.complete_picked(walk.scope(4))
    assert walk.pick() == (walk.scope(5), "background")
    assert picked_before_close[1] == "stream_attached"


def test_one_stream_left_open_keeps_the_walk_stream_attached(walk):
    walk.open_fleet_stream()
    scores_stream = walk.open_scores_stream()
    walk.submit_shell()

    detach_inference_table_stream(scores_stream.stream_token)
    walk.dispatch_pass()

    assert walk.bands() == all_at("stream_attached")


# --- T3: reopening either stream brings queued and waiting steps back ---


@pytest.mark.parametrize("open_stream", ["open_fleet_stream", "open_scores_stream"])
def test_reopening_either_stream_brings_queued_and_waiting_steps_back(walk, open_stream):
    walk.submit_shell()
    assert walk.bands() == all_at("background")

    getattr(walk, open_stream)()
    walk.submit_shell()

    assert walk.bands() == all_at("stream_attached")
    assert walk.pick() == (walk.scope(3), "stream_attached")


def test_a_stream_opened_through_scoped_connect_watches_the_walk(walk):
    walk.submit_shell()
    stream = _connect_fleet_stream(walk)
    try:
        walk.dispatch_pass()
        assert walk.bands() == all_at("stream_attached")
    finally:
        stream.close()

    walk.dispatch_pass()
    assert walk.bands() == all_at("background")


def test_the_shell_scoreboard_is_stream_attached_while_only_the_fleet_stream_is_open(walk):
    walk.open_fleet_stream()
    walk.submit_shell(analytic_id=SCORES_ANALYTIC_ID)

    assert walk.bands((SHELL_TURN,), SCORES_ANALYTIC_ID) == {SHELL_TURN: "stream_attached"}
    assert walk.bands((3, 4, 5)) == all_at("stream_attached", (3, 4, 5))


# --- T6: which shells watch which walk ---


@pytest.fixture
def homeworld_registry() -> Iterator[TableStreamRegistry]:
    registry = TableStreamRegistry()
    register_table_stream_registry("homeworld-locator", registry)
    yield registry
    reset_table_stream_registry_catalog_for_tests()
    ensure_table_stream_registries_registered()


def test_a_locator_only_shell_leaves_the_walk_at_background(walk, homeworld_registry):
    scope = FleetTableStreamScope(walk.ctx.game_id, walk.ctx.perspective, SHELL_TURN)
    attach_stream(homeworld_registry, scope, None, walk.ctx, [walk.player_id])

    walk.submit_shell()

    assert walk.bands() == all_at("background")


def test_a_later_turn_shell_keeps_the_whole_earlier_walk_stream_attached(walk):
    walk.submit_shell()
    later_turn = SHELL_TURN + 2

    walk.open_fleet_stream(later_turn)
    walk.submit_shell(later_turn)

    assert walk.bands((*WALK_TURNS, 7, 8)) == all_at("stream_attached", (*WALK_TURNS, 7, 8))


def test_an_earlier_turn_shell_leaves_the_turns_above_it_at_background(walk):
    walk.submit_shell()
    earlier_turn = 4

    walk.open_fleet_stream(earlier_turn)
    walk.submit_shell(earlier_turn)

    assert walk.bands() == {
        3: "stream_attached",
        4: "stream_attached",
        5: "background",
        6: "background",
    }


# --- T7: hops and recreated dependencies take their dependent's band ---


def test_a_persist_deferred_hop_takes_its_dependents_band(walk):
    walk.open_fleet_stream()
    walk.submit_shell()
    fleet_scope, _band = walk.pick()
    hop_scope = walk.scope(3, SCORES_ANALYTIC_ID)

    walk.orchestrator._recover_after_persist_deferred(
        walk.orchestrator.nodes[fleet_scope],
        PersistDependencyRecovery(dependency_scope=hop_scope, step_kind="tier_solve"),
    )
    walk.orchestrator.observers.drain_post_lock_callbacks()

    hop = walk.orchestrator.nodes[hop_scope]
    assert hop.standing_band == "background"
    assert walk.orchestrator.published_band(hop_scope) == "stream_attached"


def test_a_recreated_aborted_dependency_takes_its_dependents_band(walk):
    walk.open_fleet_stream()
    walk.submit_shell()
    aborted_scope, _band = walk.pick()
    walk.orchestrator.abort_scope(aborted_scope, ComputeScopeAbortedError("row run cancelled"))
    assert walk.orchestrator.nodes[aborted_scope].state == "failed"

    walk.submit_shell()

    recreated = walk.orchestrator.nodes[aborted_scope]
    assert recreated.state == "running"
    assert recreated.standing_band == "background"
    assert walk.pick() == (aborted_scope, "stream_attached")


def test_an_interactive_attach_propagates_and_a_stream_close_never_lowers_it(walk):
    fleet_stream = walk.open_fleet_stream()
    walk.submit_shell()

    walk.submit_shell(priority_band="interactive_ensure")
    detach_fleet_table_stream(fleet_stream.stream_token)
    walk.dispatch_pass()

    assert walk.bands() == all_at("interactive_ensure")
    assert walk.pick() == (walk.scope(3), "interactive_ensure")


# --- T9: the ready pick is by band, FIFO within a band ---


def test_the_ready_pick_is_by_band_then_first_in_first_out(sample_turn):
    ctx = make_fixture_query_context(sample_turn, registry=_POOL_EXPORT_REGISTRY)
    scopes = _player_scopes(sample_turn, ctx, 3)
    dispatched: list[ComputeScope] = []
    gate_open = threading.Event()
    orchestrator = ComputeOrchestrator(
        compute_registry=build_compute_registry((_single_step_thread_registration(),)),
        pool_submitter=lambda node, _step, **_kwargs: dispatched.append(node.scope),
    )
    orchestrator.observers.register_dispatch_gate(lambda _node: gate_open.is_set())
    bands: tuple[ComputeRequestBand, ...] = ("background", "interactive_ensure", "background")
    for scope, band in zip(scopes, bands, strict=True):
        orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope, priority_band=band))
    assert orchestrator.ready_scopes() == tuple(scopes)

    gate_open.set()
    for _ in scopes:
        orchestrator.dispatch_ready_work()

    assert dispatched == [scopes[1], scopes[0], scopes[2]]

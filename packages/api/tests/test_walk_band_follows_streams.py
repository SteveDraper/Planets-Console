"""A walk's band follows the live shell streams that watch it.

Most tests plan a real fleet or scoreboard walk on an orchestrator whose pool
has no workers, so queued steps wait until the test picks them. A step's band
is the one the pool would pick it at now (``published_band``), or the band a
pick returned. The T1 tests instead run a whole walk on the process
orchestrator and pool, with real steps and persists.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass, fields, replace

import pytest
from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.compute_services import turn_chain_through
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.fleet_table_stream_registry import (
    detach_fleet_table_stream,
    get_fleet_table_stream_registry,
    reset_fleet_table_stream_registry_for_tests,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.military_score_inference.inference_scheduler import (
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_domain_events import RowComplete
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    detach_inference_table_stream,
    get_inference_table_stream_registry,
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute import ComputeWorkerPool, build_compute_registry
from api.compute.errors import ComputeScopeAbortedError
from api.compute.orchestrator import ComputeHandle, ComputeOrchestrator, ComputeRequest
from api.compute.persistence import PersistDependencyRecovery
from api.compute.pools import reset_compute_worker_pool_for_tests
from api.compute.priority_band import ComputePriorityBand, ComputeRequestBand
from api.compute.runtime import get_compute_orchestrator, peek_compute_orchestrator
from api.compute.scope import ComputeScope
from api.compute.wire import StepResult
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.models.player import Score
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend
from api.streaming.table_stream.registry import TableStreamRegistry
from api.streaming.table_stream.registry_bootstrap import (
    ensure_table_stream_registries_registered,
)
from api.streaming.table_stream.registry_catalog import (
    register_table_stream_registry,
    reset_table_stream_registry_catalog_for_tests,
)
from api.streaming.table_stream.scoped_connect import iter_table_stream_connect_with_scope

from tests.compute_pool_test_helpers import complete_running_pool_step
from tests.export_chain_test_fixtures import (
    enable_backfill_earlier_turns,
    export_chain_query_context,
)
from tests.fixtures.export_framework.harness import make_fixture_query_context
from tests.fleet_exports_helpers import host_turn_at
from tests.fleet_player_scoped_gap_fill_helpers import install_mid_chain_put_ledger_gate
from tests.off_mode_catch_up_helpers import FLEET_SCORES_REGISTRY, context_at_turn
from tests.on_walk_helpers import fleet_persistence, shell_scope
from tests.on_walk_live_helpers import LiveStream, attach_stream
from tests.scores_exports_helpers import first_player_id, inference_target_player_id
from tests.test_compute_pool_published_bands import _player_scopes
from tests.test_compute_pools import _POOL_EXPORT_REGISTRY, _single_step_thread_registration

SHELL_TURN = 6
WALK_TURNS = (3, 4, 5, 6)


@pytest.fixture(autouse=True)
def _no_live_streams() -> Iterator[None]:
    reset_fleet_table_stream_registry_for_tests()
    reset_inference_table_stream_registry_for_tests()
    yield
    reset_fleet_table_stream_registry_for_tests()
    reset_inference_table_stream_registry_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)


@pytest.fixture
def walk(sample_turn) -> _Walk:
    host, ctx = context_at_turn(sample_turn, SHELL_TURN + 2)
    enable_backfill_earlier_turns(ctx)
    return _Walk(ctx, first_player_id(host))


def _open_fleet_stream(ctx, player_id: int, turn: int) -> LiveStream:
    scope = FleetTableStreamScope(ctx.game_id, ctx.perspective, turn)
    return attach_stream(get_fleet_table_stream_registry(), scope, None, ctx, [player_id])


def _open_scores_stream(ctx, player_id: int, turn: int) -> LiveStream:
    scope = InferenceStreamScope(ctx.game_id, ctx.perspective, turn)
    return attach_stream(get_inference_table_stream_registry(), scope, None, ctx, [player_id])


class _Walk:
    """One player's walks on an orchestrator whose pool never runs a step."""

    def __init__(self, ctx, player_id: int) -> None:
        self.ctx = ctx
        self.player_id = player_id
        self.pool: ComputeWorkerPool = reset_compute_worker_pool_for_tests(worker_count=0)
        self.orchestrator = ComputeOrchestrator(
            compute_registry=FLEET_SCORES_REGISTRY,
            worker_pool=self.pool,
        )

    def scope(self, turn: int, analytic_id: str = FLEET_ANALYTIC_ID) -> ComputeScope:
        return shell_scope(self.ctx, analytic_id, turn, self.player_id)

    def submit_shell(
        self,
        turn: int = SHELL_TURN,
        analytic_id: str = FLEET_ANALYTIC_ID,
        *,
        priority_band: ComputeRequestBand = "background",
    ) -> None:
        """Submit a shell the way an open stream does: force_fresh, no band of its own."""
        self.orchestrator.submit(
            ComputeRequest(
                scope=self.scope(turn, analytic_id),
                force_fresh=True,
                ctx=self.ctx,
                priority_band=priority_band,
            )
        )

    def open_fleet_stream(self, turn: int = SHELL_TURN) -> LiveStream:
        return _open_fleet_stream(self.ctx, self.player_id, turn)

    def open_scores_stream(self, turn: int = SHELL_TURN) -> LiveStream:
        return _open_scores_stream(self.ctx, self.player_id, turn)

    def dispatch_pass(self) -> None:
        self.orchestrator.dispatch_ready_work()

    def bands(
        self, turns: tuple[int, ...] = WALK_TURNS, analytic_id: str = FLEET_ANALYTIC_ID
    ) -> dict[int, ComputePriorityBand | None]:
        return {
            turn: self.orchestrator.published_band(self.scope(turn, analytic_id)) for turn in turns
        }

    def pick(self) -> tuple[ComputeScope, ComputePriorityBand]:
        picked = self.pool.take_next_item_for_tests()
        assert picked is not None
        return picked.item.scope, picked.priority_band

    def complete_picked(self, scope: ComputeScope) -> None:
        """Finish a picked step with no persist, so the next hop becomes ready."""
        complete_running_pool_step(
            self.orchestrator, scope, result_wire=StepResult(outcome="complete")
        )


def _all(band: ComputePriorityBand, turns: tuple[int, ...] = WALK_TURNS) -> dict:
    return dict.fromkeys(turns, band)


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


def _connect_fleet_stream(walk: _Walk) -> Iterator[dict[str, object]]:
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

# The sample game's ensure baseline is turn 3, so the walk hops at turns 3 and 4.
BASELINE_WALK_SHELL_TURN = 5
BASELINE_WALK_TURNS = (3, 4, 5)
WALK_GENERATION = 1
WALK_TIMEOUT_SECONDS = 30.0


@pytest.fixture
def _no_scores_row_runs() -> Iterator[None]:
    reset_tier_row_run_registry_for_tests()
    reset_inference_row_scheduler_for_tests()
    yield
    reset_tier_row_run_registry_for_tests()
    reset_inference_row_scheduler_for_tests()


def _without_scoreboard_deltas(score: Score) -> Score:
    return replace(
        score, **{field.name: 0 for field in fields(score) if field.name.endswith("change")}
    )


def _quiet_walk_context(sample_turn) -> tuple[AnalyticQueryContext, int]:
    """Backfill-on context with stored scores rows and production persist wiring.

    The walk player's scoreboard row has no deltas, so each scores step solves
    in one cheap tier and the walk's real steps and persists finish quickly.
    """
    host, _stored = host_turn_at(sample_turn, BASELINE_WALK_SHELL_TURN)
    player_id = inference_target_player_id(host)
    quiet_host = replace(
        host,
        scores=[
            _without_scoreboard_deltas(score) if score.ownerid == player_id else score
            for score in host.scores
        ],
    )
    scores_rows = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    ctx = export_chain_query_context(
        quiet_host,
        persistence=scores_rows,
        stored_turns=turn_chain_through(quiet_host),
    )
    enable_backfill_earlier_turns(ctx)
    invalidation = InferenceInvalidationService(
        scores_rows,
        fleet_persistence=fleet_persistence(ctx),
        orchestrator=peek_compute_orchestrator,
    )
    invalidation.wire_fleet_invalidation_to_persistence()
    invalidation.wire_scores_invalidation_to_fleet_persistence()
    return ctx, player_id


@dataclass(frozen=True)
class _BaselineWalk:
    """A whole fleet walk on the process orchestrator, held at its baseline hop's persist."""

    ctx: AnalyticQueryContext
    player_id: int
    fleet_stream: LiveStream
    scores_stream: LiveStream
    handle: ComputeHandle
    release_baseline_hop: threading.Event


def _start_walk_held_at_the_baseline_persist(sample_turn) -> _BaselineWalk:
    """Open both shell streams, submit the shell, and wait for the baseline hop's persist."""
    ctx, player_id = _quiet_walk_context(sample_turn)
    baseline_turn = BASELINE_WALK_TURNS[0]
    shell_settings = ctx.load_turn(BASELINE_WALK_SHELL_TURN).settings
    assert accelerated_ensure_floor(shell_settings, BASELINE_WALK_SHELL_TURN) == baseline_turn
    baseline_hop_persisting = threading.Event()
    release_baseline_hop = threading.Event()
    install_mid_chain_put_ledger_gate(
        fleet_persistence(ctx),
        player_id=player_id,
        turn_number=baseline_turn,
        leader_mid_chain=baseline_hop_persisting,
        release_leader=release_baseline_hop,
    )
    orchestrator = get_compute_orchestrator()
    shell = shell_scope(ctx, FLEET_ANALYTIC_ID, BASELINE_WALK_SHELL_TURN, player_id)
    fleet_stream = _open_fleet_stream(ctx, player_id, BASELINE_WALK_SHELL_TURN)
    scores_stream = _open_scores_stream(ctx, player_id, BASELINE_WALK_SHELL_TURN)

    handle = orchestrator.submit(ComputeRequest(scope=shell, force_fresh=True, ctx=ctx))
    assert orchestrator.published_band(shell) == "stream_attached"
    assert baseline_hop_persisting.wait(timeout=WALK_TIMEOUT_SECONDS)
    return _BaselineWalk(
        ctx=ctx,
        player_id=player_id,
        fleet_stream=fleet_stream,
        scores_stream=scores_stream,
        handle=handle,
        release_baseline_hop=release_baseline_hop,
    )


def _finish_walk(walk: _BaselineWalk) -> None:
    walk.release_baseline_hop.set()
    walk.handle.wait(timeout=WALK_TIMEOUT_SECONDS)


def _assert_walk_stamped_the_ensure_baseline_without_bumping(walk: _BaselineWalk) -> None:
    ctx, player_id = walk.ctx, walk.player_id
    persistence = fleet_persistence(ctx)
    assert walk.handle.state == "complete"
    for turn in BASELINE_WALK_TURNS:
        ledger = persistence.get_ledger(ctx.game_id, ctx.perspective, turn, player_id)
        assert ledger is not None
        assert ledger.evidence_generation == WALK_GENERATION
        assert persistence.has_final_ledger(ctx.game_id, ctx.perspective, turn, player_id)
    mark = persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id)
    assert mark.evidence_generation == WALK_GENERATION
    assert persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id) == 0
    scores_rows = ctx.export_services[SCORES_ANALYTIC_ID].persistence
    for turn in BASELINE_WALK_TURNS:
        assert scores_rows.get_row(ctx.game_id, ctx.perspective, turn, player_id) is not None


@pytest.mark.usefixtures("_no_scores_row_runs")
def test_closing_both_streams_mid_walk_still_reaches_the_ensure_baseline(sample_turn):
    walk = _start_walk_held_at_the_baseline_persist(sample_turn)

    detach_fleet_table_stream(walk.fleet_stream.stream_token)
    detach_inference_table_stream(walk.scores_stream.stream_token)
    _finish_walk(walk)

    _assert_walk_stamped_the_ensure_baseline_without_bumping(walk)


@pytest.mark.usefixtures("_no_scores_row_runs")
def test_a_walk_with_both_streams_open_reaches_the_ensure_baseline(sample_turn, caplog):
    walk = _start_walk_held_at_the_baseline_persist(sample_turn)

    with caplog.at_level(logging.ERROR):
        _finish_walk(walk)

    _assert_walk_stamped_the_ensure_baseline_without_bumping(walk)
    assert [record for record in caplog.records if record.levelno >= logging.ERROR] == []
    assert walk.fleet_stream.rescheduled_player_ids == []
    assert walk.scores_stream.rescheduled_player_ids == [walk.player_id]
    [(delivered_player_id, delivered_event)] = walk.scores_stream.delivered_events
    assert delivered_player_id == walk.player_id
    assert isinstance(delivered_event, RowComplete)


# --- T2: closing both streams drops unpicked steps to background ---


def test_closing_both_streams_drops_unpicked_steps_and_later_hops_to_background(walk):
    fleet_stream = walk.open_fleet_stream()
    scores_stream = walk.open_scores_stream()
    walk.submit_shell()
    assert walk.bands() == _all("stream_attached")
    picked_before_close = walk.pick()
    assert picked_before_close == (walk.scope(3), "stream_attached")

    detach_fleet_table_stream(fleet_stream.stream_token)
    detach_inference_table_stream(scores_stream.stream_token)
    walk.complete_picked(walk.scope(3))

    assert walk.bands((4, 5, 6)) == _all("background", (4, 5, 6))
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

    assert walk.bands() == _all("stream_attached")


# --- T3: reopening either stream brings queued and waiting steps back ---


@pytest.mark.parametrize("open_stream", ["open_fleet_stream", "open_scores_stream"])
def test_reopening_either_stream_brings_queued_and_waiting_steps_back(walk, open_stream):
    walk.submit_shell()
    assert walk.bands() == _all("background")

    getattr(walk, open_stream)()
    walk.submit_shell()

    assert walk.bands() == _all("stream_attached")
    assert walk.pick() == (walk.scope(3), "stream_attached")


def test_a_stream_opened_through_scoped_connect_watches_the_walk(walk):
    walk.submit_shell()
    stream = _connect_fleet_stream(walk)
    try:
        walk.dispatch_pass()
        assert walk.bands() == _all("stream_attached")
    finally:
        stream.close()

    walk.dispatch_pass()
    assert walk.bands() == _all("background")


def test_the_shell_scoreboard_is_stream_attached_while_only_the_fleet_stream_is_open(walk):
    walk.open_fleet_stream()
    walk.submit_shell(analytic_id=SCORES_ANALYTIC_ID)

    assert walk.bands((SHELL_TURN,), SCORES_ANALYTIC_ID) == {SHELL_TURN: "stream_attached"}
    assert walk.bands((3, 4, 5)) == _all("stream_attached", (3, 4, 5))


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

    assert walk.bands() == _all("background")


def test_a_later_turn_shell_keeps_the_whole_earlier_walk_stream_attached(walk):
    walk.submit_shell()
    later_turn = SHELL_TURN + 2

    walk.open_fleet_stream(later_turn)
    walk.submit_shell(later_turn)

    assert walk.bands((*WALK_TURNS, 7, 8)) == _all("stream_attached", (*WALK_TURNS, 7, 8))


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

    assert walk.bands() == _all("interactive_ensure")
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

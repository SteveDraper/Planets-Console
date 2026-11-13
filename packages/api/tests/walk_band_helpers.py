"""Shared walks and shell streams for the walk-band test modules.

``Walk`` plans one player's fleet or scoreboard walk on an orchestrator whose
pool has no workers, so queued steps wait until the test picks them. A step's
band is the one the pool would pick it at now (``published_band``), or the
band a pick returned. ``start_walk_held_at_the_baseline_persist`` instead runs
a whole walk on the process orchestrator and pool, with real steps and
persists.

A ``Shell`` is one shell's fleet and scoreboard streams opened the way connect
opens them: the scoreboard stream claims the scores scheduler scope first.
``end_shell`` is that connect's ``finally``.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass, fields, replace

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
    get_inference_row_scheduler,
    reset_inference_row_scheduler_for_tests,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    detach_inference_table_stream,
    get_inference_table_stream_registry,
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.scores.tier_row_run_registry import reset_tier_row_run_registry_for_tests
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute import ComputeWorkerPool
from api.compute.orchestrator import ComputeHandle, ComputeOrchestrator, ComputeRequest
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

from tests.compute_pool_test_helpers import complete_running_pool_step
from tests.export_chain_test_fixtures import (
    enable_backfill_earlier_turns,
    export_chain_query_context,
)
from tests.fleet_exports_helpers import host_turn_at
from tests.fleet_player_scoped_gap_fill_helpers import install_mid_chain_put_ledger_gate
from tests.off_mode_catch_up_helpers import FLEET_SCORES_REGISTRY, context_at_turn
from tests.on_walk_helpers import fleet_persistence, shell_scope
from tests.on_walk_live_helpers import LiveStream, attach_stream
from tests.scores_exports_helpers import first_player_id, inference_target_player_id

SHELL_TURN = 6
WALK_TURNS = (3, 4, 5, 6)


def no_live_streams() -> Iterator[None]:
    """Fixture body: no fleet or scoreboard stream is open before or after the test."""
    reset_fleet_table_stream_registry_for_tests()
    reset_inference_table_stream_registry_for_tests()
    yield
    reset_fleet_table_stream_registry_for_tests()
    reset_inference_table_stream_registry_for_tests()
    reset_compute_worker_pool_for_tests(worker_count=0)


def no_scores_row_runs() -> Iterator[None]:
    """Fixture body: no scores RowRun or scheduler claim survives from another test."""
    reset_tier_row_run_registry_for_tests()
    reset_inference_row_scheduler_for_tests()
    yield
    reset_tier_row_run_registry_for_tests()
    reset_inference_row_scheduler_for_tests()


def all_at(band: ComputePriorityBand, turns: tuple[int, ...] = WALK_TURNS) -> dict:
    return dict.fromkeys(turns, band)


def open_fleet_stream(ctx, player_id: int, turn: int) -> LiveStream:
    scope = FleetTableStreamScope(ctx.game_id, ctx.perspective, turn)
    return attach_stream(get_fleet_table_stream_registry(), scope, None, ctx, [player_id])


def open_scores_stream(ctx, player_id: int, turn: int) -> LiveStream:
    scope = InferenceStreamScope(ctx.game_id, ctx.perspective, turn)
    return attach_stream(get_inference_table_stream_registry(), scope, None, ctx, [player_id])


@dataclass(frozen=True)
class Shell:
    """One shell's open fleet and scoreboard streams."""

    scores_scope: InferenceStreamScope
    fleet_stream: LiveStream
    scores_stream: LiveStream


def open_shell(ctx, player_id: int, *, perspective: int, turn: int) -> Shell:
    """Open a shell's streams; the scoreboard stream claims the scheduler scope first."""
    scores_scope = InferenceStreamScope(ctx.game_id, perspective, turn)
    scores_token = get_inference_row_scheduler().begin_scope(scores_scope)
    scores_stream = attach_stream(
        get_inference_table_stream_registry(),
        scores_scope,
        None,
        ctx,
        [player_id],
        stream_token=scores_token,
    )
    fleet_stream = attach_stream(
        get_fleet_table_stream_registry(),
        FleetTableStreamScope(ctx.game_id, perspective, turn),
        None,
        ctx,
        [player_id],
    )
    return Shell(scores_scope=scores_scope, fleet_stream=fleet_stream, scores_stream=scores_stream)


def end_shell(shell: Shell) -> None:
    """Run the shell's connect ``finally``: each stream ends and detaches its own rows."""
    scores_token = shell.scores_stream.stream_token
    get_inference_row_scheduler().detach_inference_stream(
        shell.scores_scope, (), stream_token=scores_token
    )
    detach_inference_table_stream(scores_token)
    detach_fleet_table_stream(shell.fleet_stream.stream_token)


class Walk:
    """One player's walks on an orchestrator whose pool never runs a step."""

    def __init__(self, ctx, player_id: int) -> None:
        self.ctx = ctx
        self.player_id = player_id
        self.pool: ComputeWorkerPool = reset_compute_worker_pool_for_tests(worker_count=0)
        self.orchestrator = ComputeOrchestrator(
            compute_registry=FLEET_SCORES_REGISTRY,
            worker_pool=self.pool,
        )

    @classmethod
    def at_shell_turn(cls, sample_turn) -> Walk:
        host, ctx = context_at_turn(sample_turn, SHELL_TURN + 2)
        enable_backfill_earlier_turns(ctx)
        return cls(ctx, first_player_id(host))

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
        return open_fleet_stream(self.ctx, self.player_id, turn)

    def open_scores_stream(self, turn: int = SHELL_TURN) -> LiveStream:
        return open_scores_stream(self.ctx, self.player_id, turn)

    def open_shell(self, *, perspective: int | None = None, turn: int = SHELL_TURN) -> Shell:
        """Open a shell; the walk's own perspective unless another is named."""
        return open_shell(
            self.ctx,
            self.player_id,
            perspective=self.ctx.perspective if perspective is None else perspective,
            turn=turn,
        )

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


# --- A whole walk, held at its baseline hop's persist ---

# The sample game's ensure baseline is turn 3, so the walk hops at turns 3 and 4.
BASELINE_WALK_SHELL_TURN = 5
BASELINE_WALK_TURNS = (3, 4, 5)
WALK_GENERATION = 1
WALK_TIMEOUT_SECONDS = 30.0


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
class BaselineWalk:
    """A whole fleet walk on the process orchestrator, held at its baseline hop's persist."""

    ctx: AnalyticQueryContext
    player_id: int
    shell: Shell
    handle: ComputeHandle
    release_baseline_hop: threading.Event

    def baseline_hop(self) -> ComputeScope:
        return shell_scope(self.ctx, FLEET_ANALYTIC_ID, BASELINE_WALK_TURNS[0], self.player_id)


def start_walk_held_at_the_baseline_persist(sample_turn) -> BaselineWalk:
    """Open the shell's streams, submit the shell, and wait for the baseline hop's persist."""
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
    shell_root = shell_scope(ctx, FLEET_ANALYTIC_ID, BASELINE_WALK_SHELL_TURN, player_id)
    shell = open_shell(ctx, player_id, perspective=ctx.perspective, turn=BASELINE_WALK_SHELL_TURN)

    handle = orchestrator.submit(ComputeRequest(scope=shell_root, force_fresh=True, ctx=ctx))
    assert orchestrator.published_band(shell_root) == "stream_attached"
    assert baseline_hop_persisting.wait(timeout=WALK_TIMEOUT_SECONDS)
    return BaselineWalk(
        ctx=ctx,
        player_id=player_id,
        shell=shell,
        handle=handle,
        release_baseline_hop=release_baseline_hop,
    )


def finish_walk(walk: BaselineWalk) -> None:
    walk.release_baseline_hop.set()
    walk.handle.wait(timeout=WALK_TIMEOUT_SECONDS)


def assert_walk_stamped_the_ensure_baseline_without_bumping(walk: BaselineWalk) -> None:
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

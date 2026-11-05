"""Off-mode submission lifecycle: open turn, live streams, and a cancelled open."""

from __future__ import annotations

import pytest
from api.analytics.export_dependency_walk import is_export_scope_ensure_satisfied
from api.analytics.export_types import ExportScope
from api.analytics.fleet.compute_orchestration import (
    FleetPersistencePolicy,
    build_fleet_materialization_leg_job_wire,
)
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.fleet_table_stream_registry import (
    get_fleet_table_stream_registry,
    reset_fleet_table_stream_registry_for_tests,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
from api.analytics.fleet.types import FleetEvidenceMark
from api.analytics.scores.ensure_dependencies import resolve_scores_ensure_dependencies
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.errors import ComputeScopeAbortedError
from api.compute.orchestrator import ComputeOrchestrator, ComputeRequest
from api.compute.runtime import peek_compute_orchestrator
from api.compute.scope import ComputeScope
from api.compute.wire import DependencyOutputs
from api.exceptions import FleetScoresEvidenceOpenError
from api.serialization.backfill_earlier_turns import backfill_earlier_turns_document
from api.services.game_service import backfill_earlier_turns_store_key
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend
from api.streaming.table_stream.registry_catalog import active_table_stream_turns

from tests.fleet_exports_helpers import first_player_id
from tests.off_mode_catch_up_helpers import (
    FLEET_SCORES_REGISTRY,
    context_at_turn,
    install_submission_root,
    open_turn_fields,
    player_ledger,
    store_generation,
    write_evidence_mark,
)

_OPEN_TURN_ANALYTICS = frozenset({FLEET_ANALYTIC_ID, SCORES_ANALYTIC_ID})


def test_open_at_40_stays_the_open_when_41_has_a_live_stream(sample_turn):
    """A later live stream does not steal the submission the user opened.

    Turn 40's scoreboard solve is scheduled and that persist stamps. Turn 41
    stays on disk.
    """
    from api.analytics.fleet.exports import fleet_ensure_dependencies_for

    host, ctx = context_at_turn(sample_turn, 41)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=3,
        applies_from=40,
    )
    store_generation(persistence, ctx.game_id, ctx.perspective, 40, player_id, 3, ship_id=40)
    store_generation(persistence, ctx.game_id, ctx.perspective, 41, player_id, 1, ship_id=411)

    later_scope = FleetTableStreamScope(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn_number=41,
    )

    class _LaterStream:
        stream_token = "turn-41"

    get_fleet_table_stream_registry().attach(later_scope, _LaterStream())
    try:
        assert 41 in active_table_stream_turns(
            ctx.game_id,
            ctx.perspective,
            (FLEET_ANALYTIC_ID, SCORES_ANALYTIC_ID),
        )
        export_41 = ExportScope(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=41,
            player_id=player_id,
        )
        fleet_ensure_dependencies_for(ctx, export_41)
        resolve_scores_ensure_dependencies(ctx, export_41)
        install_submission_root(ctx.game_id, ctx.perspective, player_id, 41)

        scope_40 = ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=40,
            player_id=player_id,
        )
        wire = build_fleet_materialization_leg_job_wire(
            scope_40,
            dependency_outputs=DependencyOutputs(),
            ctx=ctx,
            open_turn=40,
        )
        assert wire["openTurn"] == 40
        assert wire["catchUp"] is False

        root_40 = install_submission_root(ctx.game_id, ctx.perspective, player_id, 40)
        invalidation = InferenceInvalidationService(
            InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
            fleet_persistence=persistence,
        )
        invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 40, player_id)
        assert persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id) == (
            FleetEvidenceMark(evidence_generation=3, applies_from_turn=40)
        )
        assert root_40.open_turn_consumed is True

        policy = FleetPersistencePolicy()
        callback = policy.persist(
            ctx,
            scope_40,
            {
                "fleetPersistLeg": "observation",
                "playerInvalidationGeneration": persistence.player_invalidation_generation(
                    ctx.game_id,
                    ctx.perspective,
                    player_id,
                ),
                **open_turn_fields(40, 40),
            },
        )
        assert callback is not None
        callback()
        later = persistence.get_ledger(ctx.game_id, ctx.perspective, 41, player_id)
        assert later is not None
        assert later.ledger.records[0].record_id == "ship-411"

        with pytest.raises(FleetScoresEvidenceOpenError) as raised:
            policy.persist(
                ctx,
                scope_40,
                {
                    "fleetPersistLeg": "finalization",
                    "persistedLedgerWire": persisted_fleet_ledger_to_json(
                        player_ledger(player_id, ship_id=40)
                    ),
                    "playerInvalidationGeneration": persistence.player_invalidation_generation(
                        ctx.game_id,
                        ctx.perspective,
                        player_id,
                    ),
                    **open_turn_fields(40, 40),
                },
            )
        recovery = raised.value.recovery
        assert recovery.dependency_scope == ComputeScope(
            analytic_id=SCORES_ANALYTIC_ID,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=40,
            player_id=player_id,
        )
        assert recovery.step_kind == "tier_solve"
        assert recovery.force_fresh is True
    finally:
        reset_fleet_table_stream_registry_for_tests()


def test_cancelled_open_does_not_classify_a_later_lower_turn_as_a_hop(sample_turn):
    """A cancelled submission that never persists is not the next open.

    The lower turn was a hop of that submission. After the submission is
    cancelled, an independent open of that turn carries its own root, its
    scoreboard persist stamps, and the cancelled turn's file stays on disk.
    """
    from api.compute import runtime as compute_runtime

    host, ctx = context_at_turn(sample_turn, 40)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=4,
        applies_from=38,
    )
    store_generation(persistence, ctx.game_id, ctx.perspective, 38, player_id, 4, ship_id=38)
    store_generation(persistence, ctx.game_id, ctx.perspective, 39, player_id, 1, ship_id=39)
    store_generation(persistence, ctx.game_id, ctx.perspective, 40, player_id, 1, ship_id=40)
    wires: list[object] = []

    def capture(_node, _step, *, job_wire=None, run_step=None) -> None:
        del run_step
        wires.append(job_wire)

    orchestrator = ComputeOrchestrator(
        compute_registry=FLEET_SCORES_REGISTRY,
        pool_submitter=capture,
    )
    scope_40 = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=40,
        player_id=player_id,
    )
    scope_39 = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=39,
        player_id=player_id,
    )
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope_40))
    assert orchestrator.nodes[scope_39].open_turn == 40
    assert orchestrator.nodes[scope_40].open_turn == 40

    for scope in list(orchestrator.nodes):
        orchestrator.abort_scope(scope, ComputeScopeAbortedError("cancelled"))

    assert (
        frozenset(
            root.open_turn
            for root in orchestrator.open_turn_roots(
                game_id=ctx.game_id,
                perspective=ctx.perspective,
                player_id=player_id,
                analytic_ids=_OPEN_TURN_ANALYTICS,
            )
        )
        == frozenset()
    )
    stored_before = persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    assert stored_before is not None and stored_before.ledger.records[0].record_id == "ship-40"

    captured_before_reopen = len(wires)
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope_39, force_fresh=True))
    reopened = orchestrator.nodes[scope_39]
    assert reopened.open_turn == 39
    assert reopened.open_turn_consumed is False
    assert frozenset(
        root.open_turn
        for root in orchestrator.open_turn_roots(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            player_id=player_id,
            analytic_ids=_OPEN_TURN_ANALYTICS,
        )
    ) == frozenset({39})
    reopened_wires = [
        wire
        for wire in wires[captured_before_reopen:]
        if isinstance(wire, dict) and wire.get("materializeTurn") == 39
    ]
    assert reopened_wires
    assert all(
        wire.get("openTurn") == 39 and wire.get("catchUp") is False for wire in reopened_wires
    )

    previous = peek_compute_orchestrator()
    compute_runtime._process_orchestrator = orchestrator
    try:
        invalidation = InferenceInvalidationService(
            InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
            fleet_persistence=persistence,
        )
        invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 39, player_id)
    finally:
        compute_runtime._process_orchestrator = previous

    assert persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id) == (
        FleetEvidenceMark(evidence_generation=4, applies_from_turn=38)
    )
    assert reopened.open_turn_consumed is True
    later = persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    assert later is not None and later.ledger.records[0].record_id == "ship-40"


def test_submission_reads_backfill_setting_once_and_carries_it(sample_turn, monkeypatch):
    """A multi-hop submit reads the record once. Nodes and the job wire carry it.

    An accepted walk keeps that value after the stored record changes.
    """
    host, ctx = context_at_turn(sample_turn, 10)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=1,
        applies_from=8,
    )
    reads: list[int] = []
    real = FleetSnapshotPersistenceService.backfill_earlier_turns_enabled

    def counting(self, game_id: int) -> bool:
        reads.append(game_id)
        return real(self, game_id)

    monkeypatch.setattr(
        FleetSnapshotPersistenceService,
        "backfill_earlier_turns_enabled",
        counting,
    )
    scope = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=10,
        player_id=player_id,
    )
    wires: list[object] = []

    def capture(_node, _step, *, job_wire=None, run_step=None) -> None:
        del run_step
        wires.append(job_wire)

    orchestrator = ComputeOrchestrator(
        compute_registry=FLEET_SCORES_REGISTRY,
        pool_submitter=capture,
    )
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=scope))

    fleet_turns = {
        node.scope.turn
        for node in orchestrator.nodes.values()
        if node.scope.analytic_id == FLEET_ANALYTIC_ID and node.scope.player_id == player_id
    }
    assert fleet_turns >= {8, 9, 10}
    assert reads == [ctx.game_id]
    assert all(node.backfill_earlier_turns is False for node in orchestrator.nodes.values())
    assert wires
    assert all(
        isinstance(wire, dict) and wire.get("backfillEarlierTurns") is False for wire in wires
    )
    hop = next(
        wire for wire in wires if isinstance(wire, dict) and wire.get("materializeTurn") != 10
    )
    assert hop["openTurn"] == 10
    assert hop["catchUp"] is True

    persistence._storage.put(
        backfill_earlier_turns_store_key(ctx.game_id),
        backfill_earlier_turns_document(True),
    )
    assert orchestrator.nodes[scope].backfill_earlier_turns is False
    assert reads == [ctx.game_id]


def _fleet_turns(orchestrator: ComputeOrchestrator, player_id: int) -> set[int]:
    return {
        node.scope.turn
        for node in orchestrator.nodes.values()
        if node.scope.analytic_id == FLEET_ANALYTIC_ID
        and node.scope.player_id == player_id
        and isinstance(node.scope.turn, int)
    }


def test_second_open_schedules_no_hop_when_priors_are_on_the_mark(sample_turn):
    """A finished catch-up hop is on the mark and still not ensure-final.

    The first open of a stale turn submits fleet hops back through
    ``appliesFromTurn``. After those hops stamp the mark, a second open of
    that turn submits no earlier hop and does not rewrite those files.
    Opening the turn after one of those hops submits that turn alone: its
    prior is on the mark, so no earlier hop is planned. Ensure-final stays
    false for every hop. The walk omits the hop because the prior is already
    on the mark.
    """
    open_turn = 41
    applies_from = 38
    mark_generation = 4
    hop_turns = (38, 39, 40)
    host, ctx = context_at_turn(sample_turn, open_turn)
    player_id = first_player_id(host)
    persistence = ctx.export_services[FLEET_ANALYTIC_ID].persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=mark_generation,
        applies_from=applies_from,
    )
    for turn in hop_turns:
        store_generation(
            persistence,
            ctx.game_id,
            ctx.perspective,
            turn,
            player_id,
            1,
            ship_id=turn,
        )

    def submit(turn: int) -> tuple[ComputeOrchestrator, list[object]]:
        wires: list[object] = []

        def capture(_node, _step, *, job_wire=None, run_step=None) -> None:
            del run_step
            wires.append(job_wire)

        orchestrator = ComputeOrchestrator(
            compute_registry=FLEET_SCORES_REGISTRY,
            pool_submitter=capture,
        )
        orchestrator.submit(
            ComputeRequest(
                ctx=ctx,
                scope=ComputeScope(
                    analytic_id=FLEET_ANALYTIC_ID,
                    game_id=ctx.game_id,
                    perspective=ctx.perspective,
                    turn=turn,
                    player_id=player_id,
                ),
            )
        )
        return orchestrator, wires

    first, first_wires = submit(open_turn)
    assert _fleet_turns(first, player_id) == {38, 39, 40, open_turn}
    assert all(node.scope.analytic_id == FLEET_ANALYTIC_ID for node in first.nodes.values())
    assert all(node.open_turn == open_turn for node in first.nodes.values())
    leaf = next(
        wire
        for wire in first_wires
        if isinstance(wire, dict) and wire.get("materializeTurn") == applies_from
    )
    assert leaf["openTurn"] == open_turn
    assert leaf["catchUp"] is True

    policy = FleetPersistencePolicy()
    epoch = persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id)
    for turn in hop_turns:
        scope = ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=turn,
            player_id=player_id,
        )
        policy.persist(
            ctx,
            scope,
            {
                "fleetPersistLeg": "observation",
                "playerInvalidationGeneration": epoch,
                **open_turn_fields(open_turn, turn),
            },
        )
        stored = persistence.get_ledger(ctx.game_id, ctx.perspective, turn, player_id)
        assert stored is not None
        finalization = policy.persist(
            ctx,
            scope,
            {
                "fleetPersistLeg": "finalization",
                "persistedLedgerWire": persisted_fleet_ledger_to_json(stored),
                "playerInvalidationGeneration": epoch,
                **open_turn_fields(open_turn, turn),
            },
        )
        assert finalization is None

    catalog = ctx.export_registry[FLEET_ANALYTIC_ID]
    hop_files = {}
    for turn in hop_turns:
        stored = persistence.get_ledger(ctx.game_id, ctx.perspective, turn, player_id)
        assert stored is not None
        assert stored.evidence_generation == mark_generation
        assert stored.provenance.is_final is False
        assert (
            is_export_scope_ensure_satisfied(
                ctx,
                FLEET_ANALYTIC_ID,
                ExportScope(
                    game_id=ctx.game_id,
                    perspective=ctx.perspective,
                    turn=turn,
                    player_id=player_id,
                ),
                catalog,
                quality="final",
            )
            is False
        )
        hop_files[turn] = persisted_fleet_ledger_to_json(stored)

    def assert_hop_files_unchanged() -> None:
        for turn, payload in hop_files.items():
            current = persistence.get_ledger(ctx.game_id, ctx.perspective, turn, player_id)
            assert current is not None
            assert persisted_fleet_ledger_to_json(current) == payload
            assert current.evidence_generation == mark_generation

    # Same turn again. Its prior is the on-mark hop at 40, which is not ensure-final.
    reopened, reopened_wires = submit(open_turn)
    reopened_root = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=open_turn,
        player_id=player_id,
    )
    assert _fleet_turns(reopened, player_id) == {open_turn}
    assert reopened.nodes[reopened_root].dependency_scopes == ()
    assert reopened_wires
    assert all(
        isinstance(wire, dict)
        and wire.get("materializeTurn") == open_turn
        and wire.get("catchUp") is False
        for wire in reopened_wires
    )
    assert_hop_files_unchanged()

    # Turn 40 is the turn after the on-mark hop at 39. Its own file stays put.
    later, later_wires = submit(40)
    assert _fleet_turns(later, player_id) == {40}
    assert len(later.nodes) == 1
    assert later_wires
    assert all(
        isinstance(wire, dict)
        and wire.get("materializeTurn") == 40
        and wire.get("catchUp") is False
        for wire in later_wires
    )
    assert_hop_files_unchanged()
    assert persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id) == (
        FleetEvidenceMark(evidence_generation=mark_generation, applies_from_turn=applies_from)
    )

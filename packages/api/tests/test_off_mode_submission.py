"""Off-mode submission lifecycle: open turn, live streams, and a cancelled open."""

from __future__ import annotations

import pytest
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
        orchestrator.in_flight_root_open_turns(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            player_id=player_id,
            analytic_ids=_OPEN_TURN_ANALYTICS,
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
    assert orchestrator.in_flight_root_open_turns(
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        player_id=player_id,
        analytic_ids=_OPEN_TURN_ANALYTICS,
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

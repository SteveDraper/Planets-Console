"""Shared setup for off-mode catch-up tests."""

from __future__ import annotations

from api.analytics.fleet import REGISTRATION as FLEET_REGISTRATION
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetEvidenceMark,
    FleetMaterializationProvenance,
    FleetShipRecord,
    FleetShipRecordFields,
    PersistedFleetLedger,
)
from api.analytics.scores import REGISTRATION as SCORES_REGISTRATION
from api.compute.dag import plan_compute_dag
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
from api.compute.registry import build_compute_registry
from api.compute.scope import ComputeScope, compute_scope_to_export_scope
from api.compute.submission_open import SubmissionOpen

from tests.export_chain_test_fixtures import export_chain_query_context
from tests.fleet_exports_helpers import host_turn_at

FLEET_SCORES_REGISTRY = build_compute_registry((FLEET_REGISTRATION, SCORES_REGISTRATION))


def player_ledger(player_id: int, *, ship_id: int) -> PersistedFleetLedger:
    return PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(
            player_id=player_id,
            records=[
                FleetShipRecord(
                    record_id=f"ship-{ship_id}",
                    fields=FleetShipRecordFields(),
                ),
            ],
        ),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=False,
            prior_ledger_at_n_minus_1=True,
        ),
        materialization_version=FLEET_MATERIALIZATION_VERSION,
    )


def store_generation(
    persistence,
    game_id,
    perspective,
    turn,
    player_id,
    generation,
    *,
    ship_id,
):
    persistence.put_ledger(
        game_id,
        perspective,
        turn,
        player_id,
        player_ledger(player_id, ship_id=ship_id),
        evidence_generation=generation,
    )


def write_evidence_mark(
    persistence,
    game_id,
    perspective,
    player_id,
    *,
    generation,
    applies_from,
):
    """Write one evidence mark without walking ledgers."""
    mark = FleetEvidenceMark(
        evidence_generation=generation,
        applies_from_turn=applies_from,
    )
    persistence._evidence_marks[(game_id, perspective, player_id)] = mark
    persistence._write_evidence_mark(game_id, perspective, player_id, mark)


def context_at_turn(sample_turn, turn_number: int):
    host, stored = host_turn_at(sample_turn, turn_number)
    ctx = export_chain_query_context(host, stored_turns=stored)
    return host, ctx


def planned_scope_keys(ctx, analytic_id, turn, player_id):
    scope = ComputeScope(
        analytic_id=analytic_id,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=turn,
        player_id=player_id,
    )
    planned = plan_compute_dag(
        ctx,
        analytic_id,
        compute_scope_to_export_scope(scope),
        compute_registry=FLEET_SCORES_REGISTRY,
        force_root=True,
        backfill_earlier_turns=ctx.backfill_earlier_turns_enabled(),
    )
    return {(node.scope.analytic_id, node.scope.turn) for node in planned}


def open_turn_fields(open_turn: int, turn: int) -> dict[str, object]:
    return {"openTurn": open_turn, "catchUp": turn < open_turn}


def install_submission_root(game_id: int, perspective: int, player_id: int, turn: int):
    """In-flight submission root whose open turn is ``turn``."""
    from api.compute import runtime as compute_runtime

    orchestrator = compute_runtime.peek_compute_orchestrator()
    if orchestrator is None:
        orchestrator = ComputeOrchestrator(compute_registry={})
        compute_runtime._process_orchestrator = orchestrator
    scope = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=game_id,
        perspective=perspective,
        turn=turn,
        player_id=player_id,
    )
    node = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state="waiting_deps",
        submission_open=SubmissionOpen(open_turn=turn),
    )
    orchestrator.nodes[scope] = node
    return node


__all__ = [
    "FLEET_SCORES_REGISTRY",
    "context_at_turn",
    "install_submission_root",
    "open_turn_fields",
    "planned_scope_keys",
    "player_ledger",
    "store_generation",
    "write_evidence_mark",
]

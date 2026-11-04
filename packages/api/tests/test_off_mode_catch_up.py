"""Off-mode catch-up: submitted scopes, stamp versus bump, and a refused late persist."""

from __future__ import annotations

from api.analytics.export_types import ExportScope
from api.analytics.fleet import REGISTRATION as FLEET_REGISTRATION
from api.analytics.fleet.compute_orchestration import FleetPersistencePolicy
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
from api.analytics.fleet.off_mode_catch_up import (
    note_off_mode_open,
    off_mode_open_turn,
)
from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetEvidenceMark,
    FleetMaterializationProvenance,
    FleetShipRecord,
    FleetShipRecordFields,
    PersistedFleetLedger,
)
from api.analytics.homeworld_locator.constants import ANALYTIC_ID as HOMEWORLD_ANALYTIC_ID
from api.analytics.homeworld_locator.exports import EXPORT_CATALOG as HOMEWORLD_EXPORT_CATALOG
from api.analytics.scores import REGISTRATION as SCORES_REGISTRATION
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.dag import plan_compute_dag
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
from api.compute.registry import build_compute_registry
from api.compute.scope import ComputeScope, compute_scope_to_export_scope
from api.exceptions import FleetStampRefused
from api.serialization.backfill_earlier_turns import backfill_earlier_turns_document
from api.services.game_service import backfill_earlier_turns_store_key
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.export_chain_test_fixtures import export_chain_query_context
from tests.fleet_exports_helpers import first_player_id, host_turn_at

_REGISTRY = build_compute_registry((FLEET_REGISTRATION, SCORES_REGISTRATION))


def _ledger(player_id: int, *, ship_id: int) -> PersistedFleetLedger:
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


def _store_generation(persistence, game_id, perspective, turn, player_id, generation, *, ship_id):
    persistence.put_ledger(
        game_id,
        perspective,
        turn,
        player_id,
        _ledger(player_id, ship_id=ship_id),
        evidence_generation=generation,
    )


def _mark_at(persistence, game_id, perspective, player_id, *, generation, applies_from):
    """Write one evidence mark without walking ledgers."""
    persistence._evidence_marks[(game_id, perspective, player_id)] = FleetEvidenceMark(
        evidence_generation=generation,
        applies_from_turn=applies_from,
    )
    persistence._write_evidence_mark(
        game_id,
        perspective,
        player_id,
        FleetEvidenceMark(evidence_generation=generation, applies_from_turn=applies_from),
    )


def _ctx_at(sample_turn, turn_number: int):
    host, stored = host_turn_at(sample_turn, turn_number)
    ctx = export_chain_query_context(host, stored_turns=stored)
    return host, ctx


def _planned_keys(ctx, analytic_id, turn, player_id):
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
        compute_registry=_REGISTRY,
        force_root=True,
    )
    return {(node.scope.analytic_id, node.scope.turn) for node in planned}


def test_stale_open_refreshes_back_through_the_mark_and_skips_scoreboard(sample_turn):
    host, ctx = _ctx_at(sample_turn, 40)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    _mark_at(
        services.persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=2,
        applies_from=38,
    )
    _store_generation(
        services.persistence, ctx.game_id, ctx.perspective, 38, player_id, 2, ship_id=38
    )
    _store_generation(
        services.persistence, ctx.game_id, ctx.perspective, 39, player_id, 1, ship_id=39
    )
    _store_generation(
        services.persistence, ctx.game_id, ctx.perspective, 41, player_id, 1, ship_id=41
    )

    planned = _planned_keys(ctx, FLEET_ANALYTIC_ID, 40, player_id)

    assert planned == {(FLEET_ANALYTIC_ID, 40), (FLEET_ANALYTIC_ID, 39)}
    assert (SCORES_ANALYTIC_ID, 39) not in planned
    assert (FLEET_ANALYTIC_ID, 41) not in planned
    assert (FLEET_ANALYTIC_ID, 38) not in planned


def test_absent_mark_does_not_walk_backward(sample_turn):
    host, ctx = _ctx_at(sample_turn, 10)
    player_id = first_player_id(host)

    planned = _planned_keys(ctx, FLEET_ANALYTIC_ID, 10, player_id)

    assert planned == {(FLEET_ANALYTIC_ID, 10)}
    assert off_mode_open_turn(ctx.game_id, ctx.perspective, player_id) == 10


def test_later_turn_uses_matching_fleet_and_does_not_invent_earlier_turns(sample_turn):
    host, ctx = _ctx_at(sample_turn, 11)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    _mark_at(
        services.persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=1,
        applies_from=10,
    )
    _store_generation(
        services.persistence, ctx.game_id, ctx.perspective, 10, player_id, 1, ship_id=10
    )

    planned = _planned_keys(ctx, SCORES_ANALYTIC_ID, 11, player_id)

    assert (FLEET_ANALYTIC_ID, 9) not in planned
    assert (FLEET_ANALYTIC_ID, 10) not in planned
    assert (SCORES_ANALYTIC_ID, 10) not in planned
    assert (SCORES_ANALYTIC_ID, 11) in planned


def test_homeworld_open_does_not_start_the_catch_up(sample_turn):
    host, ctx = _ctx_at(sample_turn, 40)
    player_id = first_player_id(host)
    dependencies = HOMEWORLD_EXPORT_CATALOG.applicable_ensure_dependencies(
        ctx,
        ExportScope(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=40,
            player_id=player_id,
        ),
    )

    assert dependencies
    assert all(dependency.analytic_id == HOMEWORLD_ANALYTIC_ID for dependency in dependencies)
    assert off_mode_open_turn(ctx.game_id, ctx.perspective, player_id) is None


def test_catch_up_hop_stamps_and_open_turn_keeps_its_generation(sample_turn):
    host, ctx = _ctx_at(sample_turn, 40)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    _mark_at(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=4,
        applies_from=38,
    )
    _store_generation(persistence, ctx.game_id, ctx.perspective, 40, player_id, 1, ship_id=40)
    note_off_mode_open(ctx.game_id, ctx.perspective, player_id, 40)
    policy = FleetPersistencePolicy()

    policy.persist(
        ctx,
        ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=39,
            player_id=player_id,
        ),
        {"fleetPersistLeg": "observation", "playerInvalidationGeneration": 0},
    )
    policy.persist(
        ctx,
        ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=40,
            player_id=player_id,
        ),
        {"fleetPersistLeg": "observation", "playerInvalidationGeneration": 0},
    )

    hop = persistence.get_ledger(ctx.game_id, ctx.perspective, 39, player_id)
    opened = persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    assert hop is not None and hop.evidence_generation == 4
    assert opened is not None and opened.evidence_generation == 1
    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 4
    )


def test_opening_turn_does_not_rewrite_a_later_turn(sample_turn):
    host, ctx = _ctx_at(sample_turn, 41)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    _mark_at(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=2,
        applies_from=40,
    )
    _store_generation(persistence, ctx.game_id, ctx.perspective, 41, player_id, 1, ship_id=411)
    note_off_mode_open(ctx.game_id, ctx.perspective, player_id, 40)
    policy = FleetPersistencePolicy()
    callback = policy.persist(
        ctx,
        ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=40,
            player_id=player_id,
        ),
        {"fleetPersistLeg": "observation", "playerInvalidationGeneration": 0},
    )
    assert callback is not None
    callback()

    later = persistence.get_ledger(ctx.game_id, ctx.perspective, 41, player_id)
    assert later is not None
    assert later.ledger.records[0].record_id == "ship-411"
    assert off_mode_open_turn(ctx.game_id, ctx.perspective, player_id) == 40


def test_catch_up_scoreboard_stamps_and_new_information_bumps(sample_turn):
    _host, ctx = _ctx_at(sample_turn, 40)
    player_id = first_player_id(sample_turn)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    _mark_at(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=3,
        applies_from=40,
    )
    _store_generation(persistence, ctx.game_id, ctx.perspective, 40, player_id, 3, ship_id=40)
    note_off_mode_open(ctx.game_id, ctx.perspective, player_id, 40)
    invalidation = InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=persistence,
    )

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 40, player_id)

    stamped = persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id)
    assert stamped == FleetEvidenceMark(evidence_generation=3, applies_from_turn=40)
    assert persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id) is not None
    assert off_mode_open_turn(ctx.game_id, ctx.perspective, player_id) is None

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 40, player_id)

    bumped = persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id)
    assert bumped.evidence_generation == 4
    assert persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id) is not None


def test_first_scoreboard_persist_sets_generation_one(sample_turn):
    _host, ctx = _ctx_at(sample_turn, 10)
    player_id = first_player_id(sample_turn)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    note_off_mode_open(ctx.game_id, ctx.perspective, player_id, 10)
    invalidation = InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=persistence,
    )

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 10, player_id)

    mark = persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id)
    assert mark == FleetEvidenceMark(evidence_generation=1, applies_from_turn=10)
    persistence.put_ledger(
        ctx.game_id,
        ctx.perspective,
        10,
        player_id,
        _ledger(player_id, ship_id=10),
    )
    stored = persistence.get_ledger(ctx.game_id, ctx.perspective, 10, player_id)
    assert stored is not None and stored.evidence_generation == 1


def test_late_persist_is_refused(sample_turn):
    host, ctx = _ctx_at(sample_turn, 40)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    _store_generation(persistence, ctx.game_id, ctx.perspective, 40, player_id, 1, ship_id=40)
    persistence.bump_player_and_turn_invalidations(
        ctx.game_id,
        ctx.perspective,
        player_id,
        (40,),
    )
    policy = FleetPersistencePolicy()

    try:
        policy.persist(
            ctx,
            ComputeScope(
                analytic_id=FLEET_ANALYTIC_ID,
                game_id=ctx.game_id,
                perspective=ctx.perspective,
                turn=40,
                player_id=player_id,
            ),
            {"fleetPersistLeg": "observation", "playerInvalidationGeneration": 0},
        )
    except FleetStampRefused:
        refused = True
    else:
        refused = False

    assert refused
    stored = persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    assert stored is not None and stored.evidence_generation == 1
    assert stored.ledger.records[0].record_id == "ship-40"


def test_bump_drops_offscreen_hops_and_refuses_an_executing_step():
    orchestrator = ComputeOrchestrator(compute_registry={})
    ready = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=1,
        perspective=1,
        turn=39,
        player_id=7,
    )
    running = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=1,
        perspective=1,
        turn=39,
        player_id=7,
    )
    shell = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=1,
        perspective=1,
        turn=40,
        player_id=7,
    )
    orchestrator.nodes[ready] = ComputeNodeRun(scope=ready, dependency_scopes=(), state="ready")
    orchestrator.nodes[running] = ComputeNodeRun(
        scope=running,
        dependency_scopes=(),
        state="running",
    )
    orchestrator.nodes[shell] = ComputeNodeRun(
        scope=shell,
        dependency_scopes=(),
        state="waiting_deps",
    )
    orchestrator._ready_queue.append(ready)

    orchestrator.discard_bumped_player_work(
        game_id=1,
        perspective=1,
        player_id=7,
        shell_turn=40,
        live_turns=frozenset(),
    )

    assert orchestrator.nodes[ready].state == "failed"
    assert ready not in orchestrator._ready_queue
    assert orchestrator.nodes[running].state == "running"
    assert orchestrator.nodes[running].discard_without_stamp is True
    assert orchestrator.nodes[shell].state == "failed"

    with orchestrator._condition:
        abandoned = orchestrator._abandon_persist_if_not_running_or_stale(
            orchestrator.nodes[running]
        )
    assert abandoned is True
    assert orchestrator.nodes[running].state == "failed"


def test_bump_wakes_the_shell_and_leaves_a_later_turn_on_disk(sample_turn, monkeypatch):
    host, ctx = _ctx_at(sample_turn, 5)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    _store_generation(persistence, ctx.game_id, ctx.perspective, 4, player_id, 1, ship_id=4)
    _store_generation(persistence, ctx.game_id, ctx.perspective, 5, player_id, 1, ship_id=5)
    note_off_mode_open(ctx.game_id, ctx.perspective, player_id, 4)
    rescheduled: list[int] = []
    woken: list[int] = []

    def spy_reschedule(scope, _player_id):
        rescheduled.append(scope.turn_number)
        return False

    def spy_wake(scope, **_kwargs):
        woken.append(scope.turn)
        return True

    monkeypatch.setattr(
        "api.services.inference_invalidation_service.reschedule_fleet_table_player",
        spy_reschedule,
    )
    monkeypatch.setattr(
        "api.services.inference_invalidation_service.wake_fleet_scope",
        spy_wake,
    )
    invalidation = InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=persistence,
    )

    invalidation.on_inference_evidence_updated(
        ctx.game_id,
        ctx.perspective,
        4,
        player_id,
        durable=True,
    )

    assert 4 in rescheduled or 4 in woken
    assert 5 not in rescheduled
    assert 5 not in woken
    later = persistence.get_ledger(ctx.game_id, ctx.perspective, 5, player_id)
    assert later is not None and later.ledger.records[0].record_id == "ship-5"


def test_backfill_on_keeps_the_final_prior_dependency(sample_turn):
    host, ctx = _ctx_at(sample_turn, 10)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    services.persistence._storage.put(
        backfill_earlier_turns_store_key(ctx.game_id),
        backfill_earlier_turns_document(True),
    )

    planned = _planned_keys(ctx, FLEET_ANALYTIC_ID, 10, player_id)

    assert (FLEET_ANALYTIC_ID, 9) in planned


def test_catch_up_hop_finalization_does_not_read_the_scoreboard(sample_turn, monkeypatch):
    host, ctx = _ctx_at(sample_turn, 40)
    player_id = first_player_id(host)
    note_off_mode_open(ctx.game_id, ctx.perspective, player_id, 40)

    def fail_scoreboard(*_args, **_kwargs):
        raise AssertionError("catch-up hop read the stored scoreboard")

    monkeypatch.setattr(
        "api.analytics.fleet.approximate_fleet.terminal_fleet_ledger",
        fail_scoreboard,
    )
    policy = FleetPersistencePolicy()
    callback = policy.persist(
        ctx,
        ComputeScope(
            analytic_id=FLEET_ANALYTIC_ID,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=39,
            player_id=player_id,
        ),
        {
            "fleetPersistLeg": "finalization",
            "persistedLedgerWire": persisted_fleet_ledger_to_json(_ledger(player_id, ship_id=39)),
        },
    )

    assert callback is None

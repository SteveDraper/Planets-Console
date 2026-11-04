"""Off-mode catch-up: submitted scopes, stamp versus bump, and a refused late persist."""

from __future__ import annotations

import pytest
from api.analytics.export_types import ExportScope
from api.analytics.fleet import REGISTRATION as FLEET_REGISTRATION
from api.analytics.fleet.compute_orchestration import (
    FleetPersistencePolicy,
    build_fleet_materialization_leg_job_wire,
)
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
from api.analytics.fleet.types import (
    STAMP_CURRENT_EVIDENCE_MARK,
    FleetAcquisitionLedger,
    FleetEvidenceMark,
    FleetMaterializationProvenance,
    FleetShipRecord,
    FleetShipRecordFields,
    PersistedFleetLedger,
)
from api.analytics.homeworld_locator.constants import ANALYTIC_ID as HOMEWORLD_ANALYTIC_ID
from api.analytics.homeworld_locator.exports import EXPORT_CATALOG as HOMEWORLD_EXPORT_CATALOG
from api.analytics.off_mode import MarkPersist, off_mode_persist_decision, parse_off_mode_wire
from api.analytics.scores import REGISTRATION as SCORES_REGISTRATION
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.dag import plan_compute_dag
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator, ComputeRequest
from api.compute.registry import build_compute_registry
from api.compute.scope import ComputeScope, compute_scope_to_export_scope
from api.compute.wire import DependencyOutputs
from api.errors import ValidationError
from api.exceptions import DiscardedWorkRefused, FleetScoresEvidenceOpenError
from api.serialization.backfill_earlier_turns import backfill_earlier_turns_document
from api.services.game_service import backfill_earlier_turns_store_key
from api.services.inference_invalidation_service import (
    InferenceInvalidationService,
    discard_bumped_player_work,
)
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


def _open_fields(open_turn: int, turn: int) -> dict[str, object]:
    return {"openTurn": open_turn, "catchUp": turn < open_turn}


def _install_open_root(game_id: int, perspective: int, player_id: int, turn: int):
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
        open_turn=turn,
    )
    orchestrator.nodes[scope] = node
    return node


def test_off_mode_persist_decision_is_one_table():
    """Scoreboard classification and the fleet merge generation share one record."""
    present = FleetEvidenceMark(evidence_generation=3, applies_from_turn=40)
    absent = FleetEvidenceMark()
    cases = (
        (
            "open turn stamps and keeps the stored generation",
            False,
            40,
            False,
            40,
            present,
            1,
            MarkPersist.STAMP,
            1,
        ),
        (
            "open turn with no file keeps generation 0",
            False,
            40,
            False,
            40,
            present,
            None,
            MarkPersist.STAMP,
            0,
        ),
        (
            "catch-up hop merge stamps; a scoreboard of that turn would bump",
            False,
            40,
            True,
            39,
            present,
            1,
            MarkPersist.BUMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "later turn bumps and stamps the merge",
            False,
            40,
            False,
            41,
            present,
            1,
            MarkPersist.BUMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "no open turn bumps",
            False,
            None,
            False,
            40,
            present,
            1,
            MarkPersist.BUMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "absent mark with no open is the first persist",
            False,
            None,
            False,
            10,
            absent,
            None,
            MarkPersist.FIRST_PERSIST,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "absent mark on the open turn is the first persist and keeps 0",
            False,
            40,
            False,
            40,
            absent,
            None,
            MarkPersist.FIRST_PERSIST,
            0,
        ),
        (
            "backfill on bumps and stamps the merge",
            True,
            40,
            False,
            40,
            present,
            1,
            MarkPersist.BUMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "backfill on an absent mark is the first persist",
            True,
            None,
            False,
            10,
            absent,
            None,
            MarkPersist.FIRST_PERSIST,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
        (
            "catch-up flag on the open turn still stamps the mark and the merge",
            False,
            40,
            True,
            40,
            present,
            1,
            MarkPersist.STAMP,
            STAMP_CURRENT_EVIDENCE_MARK,
        ),
    )
    for (
        name,
        backfill_enabled,
        open_turn,
        is_catch_up,
        host_turn,
        mark,
        stored_generation,
        mark_persist,
        merge_generation,
    ) in cases:
        decision = off_mode_persist_decision(
            backfill_enabled=backfill_enabled,
            open_turn=open_turn,
            is_catch_up=is_catch_up,
            host_turn=host_turn,
            mark=mark,
            stored_generation=stored_generation,
        )
        assert decision.mark_persist is mark_persist, name
        assert decision.merge_generation == merge_generation, name


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
        {
            "fleetPersistLeg": "observation",
            "playerInvalidationGeneration": 0,
            **_open_fields(40, 39),
        },
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
        {
            "fleetPersistLeg": "observation",
            "playerInvalidationGeneration": 0,
            **_open_fields(40, 40),
        },
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
        {
            "fleetPersistLeg": "observation",
            "playerInvalidationGeneration": 0,
            **_open_fields(40, 40),
        },
    )
    assert callback is not None
    callback()

    later = persistence.get_ledger(ctx.game_id, ctx.perspective, 41, player_id)
    assert later is not None
    assert later.ledger.records[0].record_id == "ship-411"


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
    root = _install_open_root(ctx.game_id, ctx.perspective, player_id, 40)
    invalidation = InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=persistence,
    )

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 40, player_id)

    stamped = persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id)
    assert stamped == FleetEvidenceMark(evidence_generation=3, applies_from_turn=40)
    assert persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id) is not None
    assert root.open_turn_consumed is True

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 40, player_id)

    bumped = persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id)
    assert bumped.evidence_generation == 4
    assert persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id) is not None


def test_first_scoreboard_persist_sets_generation_one(sample_turn):
    _host, ctx = _ctx_at(sample_turn, 10)
    player_id = first_player_id(sample_turn)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
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
    except DiscardedWorkRefused:
        refused = True
    else:
        refused = False

    assert refused
    stored = persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    assert stored is not None and stored.evidence_generation == 1
    assert stored.ledger.records[0].record_id == "ship-40"


def test_persist_requires_the_job_epoch(sample_turn):
    host, ctx = _ctx_at(sample_turn, 40)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    _store_generation(persistence, ctx.game_id, ctx.perspective, 40, player_id, 1, ship_id=40)
    policy = FleetPersistencePolicy()
    scope = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=40,
        player_id=player_id,
    )

    for wire in (
        {"fleetPersistLeg": "observation"},
        {"fleetPersistLeg": "observation", "playerInvalidationGeneration": True},
    ):
        try:
            policy.persist(ctx, scope, wire)
        except ValidationError as exc:
            assert "playerInvalidationGeneration" in str(exc)
        else:
            raise AssertionError("persist without an integer epoch must be rejected")

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

    discard_bumped_player_work(
        orchestrator,
        game_id=1,
        perspective=1,
        player_id=7,
        shell_turns=frozenset({40}),
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
    _install_open_root(ctx.game_id, ctx.perspective, player_id, 4)
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
            "playerInvalidationGeneration": 0,
            **_open_fields(40, 39),
        },
    )

    assert callback is None


def test_open_at_40_stays_the_open_when_41_has_a_live_stream(sample_turn):
    """A later live stream does not steal the submission the user opened.

    Turn 41 is a later turn: it is not the open, its scoreboard is not the
    catch-up that stamps, and opening 40 does not rewrite it. Turn 40's own
    scoreboard solve is still required, and that persist stamps.
    """
    from api.analytics.fleet.exports import fleet_ensure_dependencies_for
    from api.analytics.fleet.fleet_table_stream_registry import (
        get_fleet_table_stream_registry,
        reset_fleet_table_stream_registry_for_tests,
    )
    from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
    from api.analytics.scores.ensure_dependencies import resolve_scores_ensure_dependencies
    from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
    from api.streaming.table_stream.registry_catalog import active_table_stream_turns

    host, ctx = _ctx_at(sample_turn, 41)
    player_id = first_player_id(host)
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
    _store_generation(persistence, ctx.game_id, ctx.perspective, 41, player_id, 1, ship_id=411)

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
        _install_open_root(ctx.game_id, ctx.perspective, player_id, 41)

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

        root_40 = _install_open_root(ctx.game_id, ctx.perspective, player_id, 40)
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
                **_open_fields(40, 40),
            },
        )
        assert callback is not None
        callback()
        later = persistence.get_ledger(ctx.game_id, ctx.perspective, 41, player_id)
        assert later is not None
        assert later.ledger.records[0].record_id == "ship-411"

        scheduled = False
        try:
            policy.persist(
                ctx,
                scope_40,
                {
                    "fleetPersistLeg": "finalization",
                    "persistedLedgerWire": persisted_fleet_ledger_to_json(
                        _ledger(player_id, ship_id=40)
                    ),
                    "playerInvalidationGeneration": persistence.player_invalidation_generation(
                        ctx.game_id,
                        ctx.perspective,
                        player_id,
                    ),
                    **_open_fields(40, 40),
                },
            )
        except FleetScoresEvidenceOpenError:
            scheduled = True
        assert scheduled
    finally:
        reset_fleet_table_stream_registry_for_tests()


def test_submission_reads_backfill_setting_once_and_carries_it(sample_turn, monkeypatch):
    """A multi-hop submit reads the record once. Nodes and the job wire carry it.

    An accepted walk keeps that value after the stored record changes.
    """
    host, ctx = _ctx_at(sample_turn, 10)
    player_id = first_player_id(host)
    services = ctx.export_services[FLEET_ANALYTIC_ID]
    persistence = services.persistence
    _mark_at(
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

    orchestrator = ComputeOrchestrator(compute_registry=_REGISTRY, pool_submitter=capture)
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


def test_parse_off_mode_wire_rejects_wrong_types_and_catch_up_without_open_turn():
    """Absent fields stay absent. A present field of the wrong JSON type is rejected."""
    empty = parse_off_mode_wire({})
    assert empty.open_turn is None
    assert empty.catch_up is False
    assert empty.backfill_earlier_turns is None
    assert empty.player_invalidation_generation is None

    parsed = parse_off_mode_wire(
        {
            "openTurn": 40,
            "catchUp": False,
            "backfillEarlierTurns": True,
            "playerInvalidationGeneration": 2,
        }
    )
    assert parsed.open_turn == 40
    assert parsed.catch_up is False
    assert parsed.backfill_earlier_turns is True
    assert parsed.player_invalidation_generation == 2

    for wire in (
        {"openTurn": True},
        {"openTurn": 40, "catchUp": 1},
        {"backfillEarlierTurns": 0},
        {"playerInvalidationGeneration": True},
        {"catchUp": True},
    ):
        with pytest.raises(ValidationError):
            parse_off_mode_wire(wire)

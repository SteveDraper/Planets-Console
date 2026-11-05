"""In-flight open turn when a second submission joins a fleet node.

Singleflight keeps the open a hop was planned with. A submission that roots
at that same scope adopts it. Wires built after the join treat that turn as
the open: the merge keeps the stored generation, the scoreboard solve is
scheduled, and that persist stamps. A wire already built for a step inside
execution keeps the open that step started with; the next leg reads the
adopted open. Reopening the same turn, and a later higher open joining other
hops, leave the planned open in place. The backfill choice the node started
with stays.
"""

from __future__ import annotations

import pytest
from api.analytics.fleet.compute_orchestration import (
    FleetPersistencePolicy,
    build_fleet_finalization_leg_job_wire,
    build_fleet_materialization_leg_job_wire,
)
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.serialization import persisted_fleet_ledger_to_json
from api.analytics.fleet.types import FleetEvidenceMark
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeOrchestrator, ComputeRequest
from api.compute.runtime import peek_compute_orchestrator
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.compute.wire import DependencyOutputs
from api.exceptions import FleetScoresEvidenceOpenError
from api.serialization.backfill_earlier_turns import backfill_earlier_turns_document
from api.services.game_service import backfill_earlier_turns_store_key
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.fleet_exports_helpers import first_player_id
from tests.off_mode_catch_up_helpers import (
    FLEET_SCORES_REGISTRY,
    context_at_turn,
    store_generation,
    write_evidence_mark,
)

_MARK = FleetEvidenceMark(evidence_generation=4, applies_from_turn=38)


def _setup(sample_turn, *, stored: tuple[tuple[int, int, int], ...]):
    host, ctx = context_at_turn(sample_turn, 41)
    player_id = first_player_id(host)
    persistence = ctx.export_services[FLEET_ANALYTIC_ID].persistence
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=_MARK.evidence_generation,
        applies_from=_MARK.applies_from_turn,
    )
    for turn, ship_id, generation in stored:
        store_generation(
            persistence,
            ctx.game_id,
            ctx.perspective,
            turn,
            player_id,
            generation,
            ship_id=ship_id,
        )
    return ctx, player_id, persistence


def _scope(ctx, player_id: int, turn: int) -> ComputeScope:
    return ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=turn,
        player_id=player_id,
    )


def _capturing_orchestrator() -> tuple[ComputeOrchestrator, list[tuple[ComputeScope, object]]]:
    captured: list[tuple[ComputeScope, object]] = []

    def capture(node, _step, *, job_wire=None, run_step=None) -> None:
        del run_step
        captured.append((node.scope, job_wire))

    return (
        ComputeOrchestrator(
            compute_registry=FLEET_SCORES_REGISTRY,
            pool_submitter=capture,
        ),
        captured,
    )


def _submit(orchestrator: ComputeOrchestrator, ctx, player_id: int, turn: int) -> None:
    orchestrator.submit(ComputeRequest(ctx=ctx, scope=_scope(ctx, player_id, turn)))


def _fleet_open_turns(orchestrator: ComputeOrchestrator, player_id: int) -> dict[int, int | None]:
    return {
        node.scope.turn: node.submission_open.open_turn
        for node in orchestrator.nodes.values()
        if node.scope.analytic_id == FLEET_ANALYTIC_ID
        and node.scope.player_id == player_id
        and isinstance(node.scope.turn, int)
    }


def _wire_for(captured: list[tuple[ComputeScope, object]], turn: int) -> dict[str, object]:
    matches = [
        wire
        for scope, wire in captured
        if scope.analytic_id == FLEET_ANALYTIC_ID and scope.turn == turn and isinstance(wire, dict)
    ]
    assert len(matches) == 1
    return matches[0]


def _observation_wire(ctx, scope: ComputeScope, submission_open: SubmissionOpen):
    return build_fleet_materialization_leg_job_wire(
        scope,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
        submission_open=submission_open,
    )


def _assert_scoreboard_stamps(orchestrator, ctx, persistence, player_id: int, turn: int) -> None:
    from api.compute import runtime as compute_runtime

    previous = peek_compute_orchestrator()
    compute_runtime._process_orchestrator = orchestrator
    try:
        InferenceInvalidationService(
            InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
            fleet_persistence=persistence,
        ).on_scores_row_persisted(ctx.game_id, ctx.perspective, turn, player_id)
    finally:
        compute_runtime._process_orchestrator = previous
    assert persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id) == _MARK


def test_later_open_joins_hops_and_keeps_the_earlier_root(sample_turn):
    """Opening 41 while 40's hops are in flight does not steal 40's open.

    Turn 40 stays the open it was planned with, so its scoreboard persist
    stamps and the wire that leg will build is not a catch-up hop. Turn 41 is
    its own root. Shared hops keep 40. Turn 41's file stays on disk.
    """
    ctx, player_id, persistence = _setup(
        sample_turn,
        stored=((38, 38, 1), (39, 39, 1), (40, 40, 1), (41, 411, 1)),
    )
    orchestrator, captured = _capturing_orchestrator()
    scope_40 = _scope(ctx, player_id, 40)
    _submit(orchestrator, ctx, player_id, 40)
    node_38 = orchestrator.nodes[_scope(ctx, player_id, 38)]
    node_39 = orchestrator.nodes[_scope(ctx, player_id, 39)]
    node_40 = orchestrator.nodes[scope_40]
    assert _fleet_open_turns(orchestrator, player_id) == {38: 40, 39: 40, 40: 40}
    assert _wire_for(captured, 38)["openTurn"] == 40
    assert _wire_for(captured, 38)["catchUp"] is True

    _submit(orchestrator, ctx, player_id, 41)
    assert orchestrator.nodes[_scope(ctx, player_id, 38)] is node_38
    assert orchestrator.nodes[_scope(ctx, player_id, 39)] is node_39
    assert orchestrator.nodes[scope_40] is node_40
    assert _fleet_open_turns(orchestrator, player_id) == {38: 40, 39: 40, 40: 40, 41: 41}
    assert all(
        node.submission_open.backfill_earlier_turns is False for node in orchestrator.nodes.values()
    )
    assert _wire_for(captured, 38)["openTurn"] == 40
    assert frozenset(
        root.open_turn
        for root in orchestrator.open_turn_roots(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            player_id=player_id,
            analytic_ids=frozenset({FLEET_ANALYTIC_ID, SCORES_ANALYTIC_ID}),
        )
    ) == frozenset({40, 41})
    later = persistence.get_ledger(ctx.game_id, ctx.perspective, 41, player_id)
    assert later is not None and later.ledger.records[0].record_id == "ship-411"

    planned = _observation_wire(ctx, scope_40, node_40.submission_open)
    assert planned["openTurn"] == 40
    assert planned["catchUp"] is False
    _assert_scoreboard_stamps(orchestrator, ctx, persistence, player_id, 40)


def test_reopening_the_same_turn_leaves_the_running_open(sample_turn):
    """A second open of a turn whose node is already running is that same open.

    Singleflight attaches. No second hop is planned and the job wire already
    built for that node is not replaced.
    """
    ctx, player_id, _persistence = _setup(
        sample_turn,
        stored=((39, 39, 4), (40, 40, 1)),
    )
    orchestrator, captured = _capturing_orchestrator()
    scope_40 = _scope(ctx, player_id, 40)
    _submit(orchestrator, ctx, player_id, 40)
    node = orchestrator.nodes[scope_40]
    assert node.state == "running"
    assert _fleet_open_turns(orchestrator, player_id) == {40: 40}
    assert _wire_for(captured, 40)["openTurn"] == 40
    assert _wire_for(captured, 40)["catchUp"] is False
    captured_count = len(captured)

    _submit(orchestrator, ctx, player_id, 40)
    assert orchestrator.nodes[scope_40] is node
    assert node.state == "running"
    assert node.submission_open.open_turn == 40
    assert node.submission_open.backfill_earlier_turns is False
    assert _fleet_open_turns(orchestrator, player_id) == {40: 40}
    assert len(captured) == captured_count


def test_opening_a_catch_up_hop_adopts_it_as_the_open(sample_turn):
    """Opening a hop that is still in flight makes that turn the open.

    The scoreboard solve is scheduled, the merge keeps the generation already
    on the file, and the scoreboard persist stamps. Hops that are not this
    root keep the earlier open, including a step whose wire is already built.
    Flipping the stored setting does not retarget the backfill choice the node
    started with.
    """
    ctx, player_id, persistence = _setup(
        sample_turn,
        stored=((38, 38, 1), (39, 39, 1), (40, 40, 1)),
    )
    orchestrator, captured = _capturing_orchestrator()
    scope_40 = _scope(ctx, player_id, 40)
    _submit(orchestrator, ctx, player_id, 41)
    assert _fleet_open_turns(orchestrator, player_id) == {38: 41, 39: 41, 40: 41, 41: 41}
    assert orchestrator.nodes[scope_40].state == "waiting_deps"
    assert _wire_for(captured, 38)["openTurn"] == 41
    assert _wire_for(captured, 38)["catchUp"] is True

    persistence._storage.put(
        backfill_earlier_turns_store_key(ctx.game_id),
        backfill_earlier_turns_document(True),
    )
    _submit(orchestrator, ctx, player_id, 40)
    node_40 = orchestrator.nodes[scope_40]
    assert _fleet_open_turns(orchestrator, player_id) == {38: 41, 39: 41, 40: 40, 41: 41}
    assert all(
        node.submission_open.backfill_earlier_turns is False for node in orchestrator.nodes.values()
    )
    assert _wire_for(captured, 38)["catchUp"] is True
    assert frozenset(
        root.open_turn
        for root in orchestrator.open_turn_roots(
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            player_id=player_id,
            analytic_ids=frozenset({FLEET_ANALYTIC_ID, SCORES_ANALYTIC_ID}),
        )
    ) == frozenset({40, 41})

    planned = _observation_wire(ctx, scope_40, node_40.submission_open)
    assert planned["openTurn"] == 40
    assert planned["catchUp"] is False
    assert planned["backfillEarlierTurns"] is False
    policy = FleetPersistencePolicy()
    policy.persist(ctx, scope_40, {**planned, "fleetPersistLeg": "observation"})
    stored = persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    assert stored is not None and stored.evidence_generation == 1

    with pytest.raises(FleetScoresEvidenceOpenError) as raised:
        policy.persist(
            ctx,
            scope_40,
            {
                **planned,
                "fleetPersistLeg": "finalization",
                "persistedLedgerWire": persisted_fleet_ledger_to_json(stored),
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
    _assert_scoreboard_stamps(orchestrator, ctx, persistence, player_id, 40)


def test_running_hop_keeps_its_wire_and_the_next_leg_adopts_the_open(sample_turn):
    """A hop already inside observation keeps the wire that step started with.

    Adopting the open does not rebuild that wire. The following finalization
    leg is not yet inside execution, so it reads the adopted open, schedules
    the scoreboard, and that persist stamps.
    """
    ctx, player_id, persistence = _setup(
        sample_turn,
        stored=((39, 39, 4), (40, 40, 1), (41, 41, 1)),
    )
    orchestrator, captured = _capturing_orchestrator()
    scope_40 = _scope(ctx, player_id, 40)
    _submit(orchestrator, ctx, player_id, 41)
    node_40 = orchestrator.nodes[scope_40]
    assert node_40.state == "running"
    assert _fleet_open_turns(orchestrator, player_id) == {40: 41, 41: 41}
    baked = _wire_for(captured, 40)
    assert baked["openTurn"] == 41
    assert baked["catchUp"] is True

    _submit(orchestrator, ctx, player_id, 40)
    assert orchestrator.nodes[scope_40] is node_40
    assert node_40.submission_open.open_turn == 40
    assert node_40.submission_open.backfill_earlier_turns is False
    assert baked["openTurn"] == 41
    assert baked["catchUp"] is True
    assert len(captured) == 1

    policy = FleetPersistencePolicy()
    policy.persist(ctx, scope_40, {**baked, "fleetPersistLeg": "observation"})
    stored = persistence.get_ledger(ctx.game_id, ctx.perspective, 40, player_id)
    assert stored is not None and stored.evidence_generation == _MARK.evidence_generation

    final = build_fleet_finalization_leg_job_wire(
        scope_40,
        dependency_outputs=DependencyOutputs(),
        ctx=ctx,
        node_result_wire=baked,
        submission_open=node_40.submission_open,
    )
    assert final["openTurn"] == 40
    assert final["catchUp"] is False
    with pytest.raises(FleetScoresEvidenceOpenError) as raised:
        policy.persist(
            ctx,
            scope_40,
            {
                **final,
                "fleetPersistLeg": "finalization",
                "persistedLedgerWire": persisted_fleet_ledger_to_json(stored),
            },
        )
    assert raised.value.recovery.dependency_scope.turn == 40
    assert raised.value.recovery.step_kind == "tier_solve"
    _assert_scoreboard_stamps(orchestrator, ctx, persistence, player_id, 40)

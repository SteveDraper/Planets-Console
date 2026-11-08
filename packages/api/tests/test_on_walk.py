"""On-walk scope, mark, stamp, and live submit for Backfill earlier turns."""

from __future__ import annotations

import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.constants import FLEET_MATERIALIZATION_VERSION
from api.analytics.fleet.fleet_table_stream_registry import (
    get_fleet_table_stream_registry,
    reset_fleet_table_stream_registry_for_tests,
)
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.types import FleetEvidenceMark, FleetMaterializationProvenance
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    get_inference_table_stream_registry,
    reset_inference_table_stream_registry_for_tests,
)
from api.analytics.on_walk import accept_on_walk_root, reset_on_walks_for_tests
from api.analytics.on_walk_live import submit_on_walks_for_live_streams
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.analytics.turn_roster import iter_turn_players
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator
from api.compute.orchestrator_state import ResolvedComputeRequest
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.concepts.accelerated_scoreboard import accelerated_ensure_floor
from api.errors import ValidationError
from api.models.enums import PlayerStatus
from api.serialization.backfill_earlier_turns import (
    backfill_earlier_turns_document,
    backfill_earlier_turns_store_key,
)
from api.services.inference_invalidation_service import InferenceInvalidationService
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.export_chain_test_fixtures import (
    enable_backfill_earlier_turns,
    export_chain_query_context,
)
from tests.fleet_exports_helpers import host_turn_at
from tests.off_mode_catch_up_helpers import (
    FLEET_SCORES_REGISTRY,
    context_at_turn,
    planned_scope_keys,
    player_ledger,
    store_generation,
    write_evidence_mark,
)
from tests.scores_exports_helpers import first_player_id
from tests.test_fleet_eliminated_player import _stamp_player


@pytest.fixture(autouse=True)
def _clear_on_walks():
    reset_on_walks_for_tests()
    yield
    reset_on_walks_for_tests()


def _persistence(ctx):
    return ctx.export_services[FLEET_ANALYTIC_ID].persistence


def _root(ctx, analytic_id: str, turn: int, player_id: int) -> ResolvedComputeRequest:
    return ResolvedComputeRequest(
        scope=ComputeScope(
            analytic_id=analytic_id,
            game_id=ctx.game_id,
            perspective=ctx.perspective,
            turn=turn,
            player_id=player_id,
        ),
        ctx=ctx,
        submission_open=SubmissionOpen(open_turn=turn, backfill_earlier_turns=True),
    )


def _accept(ctx, analytic_id: str, turn: int, player_id: int) -> None:
    accept_on_walk_root(
        _root(ctx, analytic_id, turn, player_id), compute_registry=FLEET_SCORES_REGISTRY
    )


def _store_final(persistence, ctx, turn: int, player_id: int, generation: int) -> None:
    base = player_ledger(player_id, ship_id=turn)
    persistence.put_ledger(
        ctx.game_id,
        ctx.perspective,
        turn,
        player_id,
        replace(
            base,
            provenance=FleetMaterializationProvenance(
                turn_evidence_at_n=True,
                prior_ledger_at_n_minus_1=True,
            ),
            materialization_version=FLEET_MATERIALIZATION_VERSION,
        ),
        evidence_generation=generation,
    )


def _scores_node(
    orchestrator: ComputeOrchestrator,
    ctx,
    player_id: int,
    host_turn: int,
    *,
    open_turn: int,
    backfill: bool,
) -> None:
    scope = ComputeScope(
        analytic_id=SCORES_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=host_turn,
        player_id=player_id,
    )
    orchestrator.nodes[scope] = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state="running",
        submission_open=SubmissionOpen(open_turn=open_turn, backfill_earlier_turns=backfill),
    )


def test_on_walk_plan_refreshes_until_an_ensure_final_fleet(sample_turn):
    """Missing, approximate, and behind-mark turns stay on the walk.

    An ensure-final ledger stops the walk. A missing ledger before
    appliesFromTurn stays on it. Turns after the shell are not scheduled.
    """
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    persistence = _persistence(ctx)
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=4,
        applies_from=8,
    )
    for turn in (1, 2, 3):
        _store_final(persistence, ctx, turn, player_id, 4)
    store_generation(
        persistence,
        ctx.game_id,
        ctx.perspective,
        7,
        player_id,
        1,
        ship_id=7,
    )
    _store_final(persistence, ctx, 8, player_id, 1)

    planned = planned_scope_keys(ctx, FLEET_ANALYTIC_ID, 10, player_id)

    assert (FLEET_ANALYTIC_ID, 4) in planned
    assert (FLEET_ANALYTIC_ID, 6) in planned
    assert (FLEET_ANALYTIC_ID, 7) in planned
    assert (FLEET_ANALYTIC_ID, 8) in planned
    assert (FLEET_ANALYTIC_ID, 10) in planned
    assert (FLEET_ANALYTIC_ID, 3) not in planned
    assert (FLEET_ANALYTIC_ID, 1) not in planned
    assert (FLEET_ANALYTIC_ID, 11) not in planned


def test_scoreboard_on_walk_includes_the_prior_fleet(sample_turn):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)

    planned = planned_scope_keys(ctx, SCORES_ANALYTIC_ID, 10, player_id)

    assert (SCORES_ANALYTIC_ID, 10) in planned
    assert (FLEET_ANALYTIC_ID, 9) in planned
    assert (FLEET_ANALYTIC_ID, 11) not in planned
    assert (SCORES_ANALYTIC_ID, 11) not in planned


def test_eliminated_shell_player_has_no_prior_fleet(sample_turn):
    shell_turn = 10
    stamped = _stamp_player(
        sample_turn,
        first_player_id(sample_turn),
        status=int(PlayerStatus.ELIMINATED),
        statusturn=shell_turn,
        turn_number=shell_turn,
    )
    host, ctx = context_at_turn(stamped, shell_turn)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)

    fleet_plan = planned_scope_keys(ctx, FLEET_ANALYTIC_ID, shell_turn, player_id)
    scores_plan = planned_scope_keys(ctx, SCORES_ANALYTIC_ID, shell_turn, player_id)

    assert (FLEET_ANALYTIC_ID, shell_turn - 1) not in fleet_plan
    assert (FLEET_ANALYTIC_ID, shell_turn - 1) not in scores_plan
    _accept(ctx, FLEET_ANALYTIC_ID, shell_turn, player_id)
    assert (
        _persistence(ctx).evidence_mark(ctx.game_id, ctx.perspective, player_id)
        == FleetEvidenceMark()
    )


def test_unstored_dependency_turn_keeps_the_plan_floor(sample_turn):
    host, stored = host_turn_at(sample_turn, 5)
    del stored[3]
    ctx = export_chain_query_context(host, stored_turns=stored)
    enable_backfill_earlier_turns(ctx)

    with pytest.raises(ValidationError, match="turn unavailable"):
        planned_scope_keys(ctx, FLEET_ANALYTIC_ID, 5, first_player_id(host))


def test_absent_mark_is_generation_one_at_the_baseline_before_persist(sample_turn):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    persistence = _persistence(ctx)
    baseline = accelerated_ensure_floor(host.settings, 10)

    _accept(ctx, FLEET_ANALYTIC_ID, 10, player_id)
    assert persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id) == FleetEvidenceMark(
        evidence_generation=1,
        applies_from_turn=baseline,
    )

    _accept(ctx, SCORES_ANALYTIC_ID, 10, player_id)
    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 1
    )


def test_existing_mark_moves_applies_from_backward_only(sample_turn):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    persistence = _persistence(ctx)
    write_evidence_mark(
        persistence,
        ctx.game_id,
        ctx.perspective,
        player_id,
        generation=4,
        applies_from=8,
    )
    for turn in (1, 2, 3):
        _store_final(persistence, ctx, turn, player_id, 4)

    _accept(ctx, FLEET_ANALYTIC_ID, 10, player_id)
    assert persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id) == FleetEvidenceMark(
        evidence_generation=4,
        applies_from_turn=4,
    )

    # A later plan whose earliest turn is higher must not move the bound forward.
    final_at_bound = replace(
        player_ledger(player_id, ship_id=4),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=True,
            prior_ledger_at_n_minus_1=True,
        ),
        evidence_generation=4,
    )
    persistence._write_player_ledger(ctx.game_id, ctx.perspective, 4, player_id, final_at_bound)
    _accept(ctx, FLEET_ANALYTIC_ID, 10, player_id)
    assert persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id) == FleetEvidenceMark(
        evidence_generation=4,
        applies_from_turn=4,
    )


def test_on_walk_scoreboard_persist_stamps_and_a_stray_persist_bumps(sample_turn):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    persistence = _persistence(ctx)
    _accept(ctx, FLEET_ANALYTIC_ID, 10, player_id)
    orchestrator = ComputeOrchestrator(compute_registry={})
    _scores_node(orchestrator, ctx, player_id, 10, open_turn=10, backfill=True)
    _scores_node(orchestrator, ctx, player_id, 6, open_turn=10, backfill=True)
    invalidation = InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=persistence,
        orchestrator=lambda: orchestrator,
    )

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 10, player_id)
    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 6, player_id)

    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 1
    )
    assert persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id) == 0

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 11, player_id)

    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 2
    )
    assert persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id) == 1


def test_two_open_turns_stamp_without_discarding_each_other(sample_turn):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    persistence = _persistence(ctx)
    _accept(ctx, FLEET_ANALYTIC_ID, 10, player_id)
    _accept(ctx, SCORES_ANALYTIC_ID, 8, player_id)
    orchestrator = ComputeOrchestrator(compute_registry={})
    _scores_node(orchestrator, ctx, player_id, 10, open_turn=10, backfill=True)
    _scores_node(orchestrator, ctx, player_id, 8, open_turn=8, backfill=True)
    invalidation = InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
        fleet_persistence=persistence,
        orchestrator=lambda: orchestrator,
    )

    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 10, player_id)
    invalidation.on_scores_row_persisted(ctx.game_id, ctx.perspective, 8, player_id)

    assert (
        persistence.evidence_mark(ctx.game_id, ctx.perspective, player_id).evidence_generation == 1
    )
    assert persistence.player_invalidation_generation(ctx.game_id, ctx.perspective, player_id) == 0


class _EventQueue:
    def __init__(self) -> None:
        self.events: list[object] = []

    def put(self, event: object) -> None:
        self.events.append(event)


def _player_ids(turn) -> list[int]:
    return [player.id for player in iter_turn_players(turn)]


def _attach_stream(registry, scope, turn, ctx, player_ids: list[int]):
    rows = {}
    for player_id in player_ids:
        rows[player_id] = SimpleNamespace(session=SimpleNamespace(event_queue=_EventQueue()))
    controller = SimpleNamespace(
        turn=turn,
        query_context=ctx,
        scheduled_rows=rows,
        wake_multiplex=threading.Event(),
    )
    registry.attach(scope, controller)
    return controller


def _recording_orchestrator(monkeypatch) -> tuple[ComputeOrchestrator, list]:
    orchestrator = ComputeOrchestrator(compute_registry={})
    submitted: list = []

    def record(request):
        submitted.append(request)

    monkeypatch.setattr(orchestrator, "submit", record)
    return orchestrator, submitted


def test_live_streams_submit_one_force_fresh_walk_per_player(sample_turn, monkeypatch):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_ids = _player_ids(host)
    fleet_scope = FleetTableStreamScope(ctx.game_id, ctx.perspective, 10)
    scores_scope = InferenceStreamScope(ctx.game_id, ctx.perspective, 10)
    fleet = _attach_stream(get_fleet_table_stream_registry(), fleet_scope, host, ctx, player_ids)
    scores = _attach_stream(
        get_inference_table_stream_registry(), scores_scope, host, ctx, player_ids
    )
    orchestrator, submitted = _recording_orchestrator(monkeypatch)
    try:
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
    finally:
        reset_fleet_table_stream_registry_for_tests()
        reset_inference_table_stream_registry_for_tests()

    by_player: dict[int, set[str]] = {}
    for request in submitted:
        assert request.force_fresh is True
        assert request.priority_band == "stream_attached"
        assert request.submission_open is None
        assert request.scope.turn == 10
        by_player.setdefault(request.scope.player_id, set()).add(request.scope.analytic_id)
    assert set(by_player) == set(player_ids)
    assert all(
        analytics == {FLEET_ANALYTIC_ID, SCORES_ANALYTIC_ID} for analytics in by_player.values()
    )
    assert fleet.wake_multiplex.is_set()
    assert scores.wake_multiplex.is_set()
    for player_id in player_ids:
        assert (
            fleet.scheduled_rows[player_id].session.event_queue.events[0]["type"] == "work_accepted"
        )
        assert (
            scores.scheduled_rows[player_id].session.event_queue.events[0]["type"]
            == "work_accepted"
        )


def test_no_live_stream_does_not_create_an_orchestrator(sample_turn, monkeypatch):
    _host, ctx = context_at_turn(sample_turn, 10)

    def refuse():
        raise AssertionError("orchestrator created")

    monkeypatch.setattr("api.analytics.on_walk_live.get_compute_orchestrator", refuse)
    get_fleet_table_stream_registry().attach(
        FleetTableStreamScope(ctx.game_id, ctx.perspective, 10),
        object(),
    )
    try:
        submit_on_walks_for_live_streams(ctx.game_id)
    finally:
        reset_fleet_table_stream_registry_for_tests()


def test_off_setting_fleet_defers_one_player_until_the_node_is_terminal(sample_turn, monkeypatch):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_ids = _player_ids(host)
    assert len(player_ids) >= 2
    blocked = player_ids[0]
    free = player_ids[1]
    _attach_stream(
        get_fleet_table_stream_registry(),
        FleetTableStreamScope(ctx.game_id, ctx.perspective, 10),
        host,
        ctx,
        player_ids,
    )
    orchestrator, submitted = _recording_orchestrator(monkeypatch)
    blocker = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=9,
        player_id=blocked,
    )
    node = ComputeNodeRun(
        scope=blocker,
        dependency_scopes=(),
        state="running",
        submission_open=SubmissionOpen(open_turn=10, backfill_earlier_turns=False),
    )
    orchestrator.nodes[blocker] = node
    try:
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
        submitted_ids = {request.scope.player_id for request in submitted}
        assert free in submitted_ids
        assert blocked not in submitted_ids

        node.state = "parked"
        orchestrator.observers.notify_scope_outcome(node)
        orchestrator.observers.drain_post_lock_callbacks()
        assert blocked not in {request.scope.player_id for request in submitted}

        node.state = "failed"
        orchestrator.observers.notify_scope_outcome(node)
        orchestrator.observers.drain_post_lock_callbacks()
        assert blocked in {request.scope.player_id for request in submitted}
        blocked_request = next(
            request for request in submitted if request.scope.player_id == blocked
        )
        assert blocked_request.force_fresh is True
        assert blocked_request.priority_band == "stream_attached"
    finally:
        reset_fleet_table_stream_registry_for_tests()


def test_deferred_on_walk_skips_a_closed_stream_or_a_setting_that_turned_off(
    sample_turn, monkeypatch
):
    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    scope = FleetTableStreamScope(ctx.game_id, ctx.perspective, 10)
    _attach_stream(get_fleet_table_stream_registry(), scope, host, ctx, [player_id])
    orchestrator, submitted = _recording_orchestrator(monkeypatch)
    blocker = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=9,
        player_id=player_id,
    )
    node = ComputeNodeRun(
        scope=blocker,
        dependency_scopes=(),
        state="running",
        submission_open=SubmissionOpen(backfill_earlier_turns=False),
    )
    orchestrator.nodes[blocker] = node
    try:
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
        assert player_id not in {request.scope.player_id for request in submitted}
        _persistence(ctx)._storage.put(
            backfill_earlier_turns_store_key(ctx.game_id),
            backfill_earlier_turns_document(False),
        )
        node.state = "complete"
        orchestrator.observers.notify_scope_outcome(node)
        orchestrator.observers.drain_post_lock_callbacks()
        assert player_id not in {request.scope.player_id for request in submitted}
    finally:
        reset_fleet_table_stream_registry_for_tests()

    host, ctx = context_at_turn(sample_turn, 10)
    enable_backfill_earlier_turns(ctx)
    player_id = first_player_id(host)
    scope = FleetTableStreamScope(ctx.game_id, ctx.perspective, 10)
    _attach_stream(get_fleet_table_stream_registry(), scope, host, ctx, [player_id])
    orchestrator, submitted = _recording_orchestrator(monkeypatch)
    blocker = ComputeScope(
        analytic_id=FLEET_ANALYTIC_ID,
        game_id=ctx.game_id,
        perspective=ctx.perspective,
        turn=9,
        player_id=player_id,
    )
    node = ComputeNodeRun(
        scope=blocker,
        dependency_scopes=(),
        state="running",
        submission_open=SubmissionOpen(backfill_earlier_turns=False),
    )
    orchestrator.nodes[blocker] = node
    try:
        submit_on_walks_for_live_streams(ctx.game_id, orchestrator=orchestrator)
        assert player_id not in {request.scope.player_id for request in submitted}
        reset_fleet_table_stream_registry_for_tests()
        node.state = "failed"
        orchestrator.observers.notify_scope_outcome(node)
        orchestrator.observers.drain_post_lock_callbacks()
        assert player_id not in {request.scope.player_id for request in submitted}
    finally:
        reset_fleet_table_stream_registry_for_tests()

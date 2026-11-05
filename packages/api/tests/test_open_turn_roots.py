"""Orchestrator open-turn root query and the caller's analytic precedence."""

from __future__ import annotations

from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute import runtime as compute_runtime
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator, OpenTurnRoot
from api.compute.orchestrator_state import NodeState
from api.compute.scope import ComputeScope
from api.services.inference_invalidation_service import (
    InferenceInvalidationService,
    preferred_unconsumed_root_backfill,
)
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

_ANALYTICS = frozenset({"alpha", "beta"})


def _put(
    orchestrator: ComputeOrchestrator,
    analytic_id: str,
    turn: int,
    *,
    player_id: int = 7,
    game_id: int = 1,
    perspective: int = 1,
    open_turn: int | None = None,
    backfill: bool = False,
    consumed: bool = False,
    state: NodeState = "ready",
) -> ComputeScope:
    scope = ComputeScope(
        analytic_id=analytic_id,
        game_id=game_id,
        perspective=perspective,
        turn=turn,
        player_id=player_id,
    )
    orchestrator.nodes[scope] = ComputeNodeRun(
        scope=scope,
        dependency_scopes=(),
        state=state,
        open_turn=open_turn,
        open_turn_consumed=consumed,
        backfill_earlier_turns=backfill,
    )
    return scope


def _roots(
    orchestrator: ComputeOrchestrator,
    *,
    turn: int | None = None,
    analytic_ids: frozenset[str] = _ANALYTICS,
    player_id: int = 7,
) -> tuple[OpenTurnRoot, ...]:
    return orchestrator.open_turn_roots(
        game_id=1,
        perspective=1,
        player_id=player_id,
        analytic_ids=analytic_ids,
        turn=turn,
    )


def test_open_turn_roots_returns_each_in_flight_root():
    orchestrator = ComputeOrchestrator(compute_registry={})
    _put(orchestrator, "alpha", 40, open_turn=40, backfill=True)
    _put(orchestrator, "alpha", 39, open_turn=40, backfill=True)
    _put(orchestrator, "beta", 40, open_turn=40, backfill=False, consumed=True)
    _put(orchestrator, "alpha", 41, open_turn=41, state="complete")
    _put(orchestrator, "alpha", 40, open_turn=40, player_id=8)
    _put(orchestrator, "alpha", 40, open_turn=40, game_id=2)
    _put(orchestrator, "gamma", 40, open_turn=40, backfill=True)
    wild = ComputeScope(
        analytic_id="alpha",
        game_id=1,
        perspective=1,
        turn="*",
        player_id=7,
    )
    orchestrator.nodes[wild] = ComputeNodeRun(
        scope=wild,
        dependency_scopes=(),
        open_turn=40,
        backfill_earlier_turns=True,
    )

    assert _roots(orchestrator) == (
        OpenTurnRoot(
            analytic_id="alpha",
            open_turn=40,
            backfill_earlier_turns=True,
            consumed=False,
        ),
        OpenTurnRoot(
            analytic_id="beta",
            open_turn=40,
            backfill_earlier_turns=False,
            consumed=True,
        ),
    )
    assert _roots(orchestrator, turn=41) == ()
    assert _roots(orchestrator, player_id=8) == (
        OpenTurnRoot(
            analytic_id="alpha",
            open_turn=40,
            backfill_earlier_turns=False,
            consumed=False,
        ),
    )


def test_consume_open_turn_roots_marks_only_matching_roots():
    orchestrator = ComputeOrchestrator(compute_registry={})
    root = _put(orchestrator, "alpha", 40, open_turn=40)
    hop = _put(orchestrator, "alpha", 39, open_turn=40)
    finished = _put(orchestrator, "delta", 40, open_turn=40, state="complete")
    other = _put(orchestrator, "gamma", 40, open_turn=40)
    adopted = _put(orchestrator, "beta", 40, open_turn=41)

    orchestrator.consume_open_turn_roots(
        game_id=1,
        perspective=1,
        player_id=7,
        open_turn=40,
        analytic_ids=frozenset({"alpha", "beta", "delta"}),
    )

    assert orchestrator.nodes[root].open_turn_consumed is True
    assert orchestrator.nodes[hop].open_turn_consumed is False
    # Consume records the one-shot on a finished root. The query omits finished roots.
    assert orchestrator.nodes[finished].open_turn_consumed is True
    assert orchestrator.nodes[other].open_turn_consumed is False
    assert orchestrator.nodes[adopted].open_turn_consumed is False
    assert _roots(orchestrator, analytic_ids=frozenset({"alpha"})) == (
        OpenTurnRoot(
            analytic_id="alpha",
            open_turn=40,
            backfill_earlier_turns=False,
            consumed=True,
        ),
    )


def test_discard_matching_work_uses_the_player_scan():
    orchestrator = ComputeOrchestrator(compute_registry={})
    ready = _put(orchestrator, "alpha", 39)
    running = _put(orchestrator, "alpha", 38, state="running")
    other = _put(orchestrator, "gamma", 39)
    wild = ComputeScope(
        analytic_id="alpha",
        game_id=1,
        perspective=1,
        turn="*",
        player_id=7,
    )
    orchestrator.nodes[wild] = ComputeNodeRun(scope=wild, dependency_scopes=(), state="ready")
    orchestrator._ready_queue.append(ready)

    orchestrator.discard_matching_work(
        lambda _scope, _node: True,
        game_id=1,
        perspective=1,
        player_id=7,
        analytic_ids=frozenset({"alpha"}),
    )

    assert orchestrator.nodes[ready].state == "failed"
    assert ready not in orchestrator._ready_queue
    assert orchestrator.nodes[running].state == "running"
    assert orchestrator.nodes[running].discard_without_stamp is True
    assert orchestrator.nodes[other].state == "ready"
    assert orchestrator.nodes[wild].state == "ready"


def test_preferred_unconsumed_root_backfill_lets_the_caller_choose():
    fleet = OpenTurnRoot(
        analytic_id=FLEET_ANALYTIC_ID,
        open_turn=40,
        backfill_earlier_turns=False,
        consumed=False,
    )
    scores = OpenTurnRoot(
        analytic_id=SCORES_ANALYTIC_ID,
        open_turn=40,
        backfill_earlier_turns=True,
        consumed=False,
    )
    assert (
        preferred_unconsumed_root_backfill(
            (fleet, scores),
            host_turn=40,
            preferred_analytic_id=SCORES_ANALYTIC_ID,
        )
        is True
    )
    assert (
        preferred_unconsumed_root_backfill(
            (scores, fleet),
            host_turn=40,
            preferred_analytic_id=SCORES_ANALYTIC_ID,
        )
        is True
    )
    consumed_scores = OpenTurnRoot(
        analytic_id=SCORES_ANALYTIC_ID,
        open_turn=40,
        backfill_earlier_turns=True,
        consumed=True,
    )
    assert (
        preferred_unconsumed_root_backfill(
            (consumed_scores, fleet),
            host_turn=40,
            preferred_analytic_id=SCORES_ANALYTIC_ID,
        )
        is False
    )
    later = OpenTurnRoot(
        analytic_id="beta",
        open_turn=40,
        backfill_earlier_turns=True,
        consumed=False,
    )
    assert (
        preferred_unconsumed_root_backfill(
            (fleet, later),
            host_turn=40,
            preferred_analytic_id=SCORES_ANALYTIC_ID,
        )
        is True
    )
    assert (
        preferred_unconsumed_root_backfill(
            (consumed_scores,),
            host_turn=40,
            preferred_analytic_id=SCORES_ANALYTIC_ID,
        )
        is None
    )


def test_carried_submission_backfill_prefers_the_scores_root():
    orchestrator = ComputeOrchestrator(compute_registry={})
    _put(
        orchestrator,
        FLEET_ANALYTIC_ID,
        40,
        open_turn=40,
        backfill=False,
    )
    _put(
        orchestrator,
        SCORES_ANALYTIC_ID,
        40,
        open_turn=40,
        backfill=True,
    )
    service = InferenceInvalidationService(
        InferenceRowPersistenceService(MemoryAssetBackend(initial={})),
    )
    previous = compute_runtime._process_orchestrator
    compute_runtime._process_orchestrator = orchestrator
    try:
        assert service._carried_submission_backfill(1, 1, 7, 40) is True
        assert service._unconsumed_submission_open(1, 1, 7, 40) == 40
    finally:
        compute_runtime._process_orchestrator = previous

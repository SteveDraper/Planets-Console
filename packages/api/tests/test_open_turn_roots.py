"""Orchestrator open-turn root query and the caller's analytic precedence."""

from __future__ import annotations

import threading

from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeNodeRun, ComputeOrchestrator, OpenTurnRoot
from api.compute.orchestrator_state import NodeState
from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.services.inference_invalidation_service import (
    preferred_unconsumed_root_backfill,
    resolve_durable_scores_evidence,
)

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
        submission_open=SubmissionOpen(
            open_turn=open_turn,
            backfill_earlier_turns=backfill,
        ),
        open_turn_consumed=consumed,
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
        submission_open=SubmissionOpen(open_turn=40, backfill_earlier_turns=True),
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
    orchestrator.nodes[wild] = ComputeNodeRun(
        scope=wild, dependency_scopes=(), state="ready", submission_open=SubmissionOpen()
    )
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


def test_resolve_durable_scores_evidence_splits_carried_choice_from_wake_record():
    """Stamp reads the carried root. Wake reads the current record and the claim snapshot."""
    fleet = OpenTurnRoot(
        analytic_id=FLEET_ANALYTIC_ID,
        open_turn=40,
        backfill_earlier_turns=True,
        consumed=False,
    )
    scores = OpenTurnRoot(
        analytic_id=SCORES_ANALYTIC_ID,
        open_turn=40,
        backfill_earlier_turns=False,
        consumed=False,
    )
    preferred = resolve_durable_scores_evidence(
        (fleet, scores),
        host_turn=40,
        wake_backfill=False,
        live_turns=frozenset({40}),
    )
    assert preferred.decision_backfill is False
    assert preferred.wake_backfill is False
    assert preferred.chosen is not None
    assert preferred.chosen.limited is not None

    early_shell = OpenTurnRoot(
        analytic_id=FLEET_ANALYTIC_ID,
        open_turn=39,
        backfill_earlier_turns=True,
        consumed=False,
    )
    evidence = resolve_durable_scores_evidence(
        (early_shell, scores),
        host_turn=40,
        wake_backfill=False,
        live_turns=frozenset({39, 40}),
    )
    assert evidence.open_turn == 40
    assert evidence.decision_backfill is False
    assert evidence.wake_backfill is False
    assert evidence.chosen is not None
    limited = evidence.chosen.limited
    assert limited is not None
    assert limited.shell_turns == frozenset({39, 40})
    assert limited.live_turns == frozenset({39, 40})
    assert limited.turns == frozenset({40})

    # The current record wakes every known turn even when the carried choice is off.
    woken = resolve_durable_scores_evidence(
        (scores,),
        host_turn=40,
        wake_backfill=True,
        live_turns=frozenset(),
    )
    assert woken.decision_backfill is False
    assert woken.wake_backfill is True
    assert woken.chosen is not None
    assert woken.chosen.limited is None

    consumed = OpenTurnRoot(
        analytic_id=SCORES_ANALYTIC_ID,
        open_turn=40,
        backfill_earlier_turns=True,
        consumed=True,
    )
    absent = resolve_durable_scores_evidence(
        (consumed,),
        host_turn=40,
        wake_backfill=True,
        live_turns=frozenset({40}),
    )
    assert absent.open_turn is None
    assert absent.decision_backfill is None
    assert absent.wake_backfill is True
    assert absent.chosen is None
    carried = preferred_unconsumed_root_backfill(
        (consumed,),
        host_turn=40,
        preferred_analytic_id=SCORES_ANALYTIC_ID,
    )
    assert carried is None


def test_claim_open_turn_roots_consumes_under_one_lock_and_keeps_the_preimage():
    orchestrator = ComputeOrchestrator(compute_registry={})
    root = _put(orchestrator, "alpha", 40, open_turn=40, backfill=True)
    hop = _put(orchestrator, "alpha", 39, open_turn=40, backfill=True)
    other = _put(orchestrator, "alpha", 41, open_turn=41)
    seen: list[tuple[OpenTurnRoot, ...]] = []

    def consume(roots: tuple[OpenTurnRoot, ...]) -> bool:
        seen.append(roots)
        assert any(not item.consumed and item.open_turn == 40 for item in roots)
        return True

    snapshot = orchestrator.claim_open_turn_roots(
        game_id=1,
        perspective=1,
        player_id=7,
        open_turn=40,
        analytic_ids=_ANALYTICS,
        consume=consume,
    )

    assert snapshot == seen[0]
    assert any(item.open_turn == 40 and item.consumed is False for item in snapshot)
    assert orchestrator.nodes[root].open_turn_consumed is True
    assert orchestrator.nodes[hop].open_turn_consumed is False
    assert orchestrator.nodes[other].open_turn_consumed is False

    def second(roots: tuple[OpenTurnRoot, ...]) -> bool:
        seen.append(roots)
        assert all(item.consumed for item in roots if item.open_turn == 40)
        assert any(not item.consumed and item.open_turn == 41 for item in roots)
        return True

    orchestrator.claim_open_turn_roots(
        game_id=1,
        perspective=1,
        player_id=7,
        open_turn=40,
        analytic_ids=_ANALYTICS,
        consume=second,
    )
    assert orchestrator.nodes[other].open_turn_consumed is False


def test_claim_open_turn_roots_declines_without_consuming():
    orchestrator = ComputeOrchestrator(compute_registry={})
    root = _put(orchestrator, "alpha", 40, open_turn=40)

    snapshot = orchestrator.claim_open_turn_roots(
        game_id=1,
        perspective=1,
        player_id=7,
        open_turn=40,
        analytic_ids=_ANALYTICS,
        consume=lambda _roots: False,
    )

    assert snapshot[0].consumed is False
    assert orchestrator.nodes[root].open_turn_consumed is False


def test_claim_open_turn_roots_blocks_a_second_claim_until_consume():
    orchestrator = ComputeOrchestrator(compute_registry={})
    _put(orchestrator, "alpha", 40, open_turn=40)
    entered = threading.Event()
    second_snapshot: list[tuple[OpenTurnRoot, ...]] = []

    def second_claim() -> None:
        def observe(roots: tuple[OpenTurnRoot, ...]) -> bool:
            second_snapshot.append(roots)
            return False

        entered.set()
        orchestrator.claim_open_turn_roots(
            game_id=1,
            perspective=1,
            player_id=7,
            open_turn=40,
            analytic_ids=_ANALYTICS,
            consume=observe,
        )

    worker = threading.Thread(target=second_claim, daemon=True)

    def first(roots: tuple[OpenTurnRoot, ...]) -> bool:
        assert any(not item.consumed for item in roots)
        worker.start()
        assert entered.wait(timeout=1)
        worker.join(timeout=0.2)
        assert worker.is_alive()
        return True

    orchestrator.claim_open_turn_roots(
        game_id=1,
        perspective=1,
        player_id=7,
        open_turn=40,
        analytic_ids=_ANALYTICS,
        consume=first,
    )
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert second_snapshot
    assert all(item.consumed for item in second_snapshot[0] if item.open_turn == 40)

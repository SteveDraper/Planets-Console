"""Coordinate scores inference persistence invalidation and in-place stream reschedule."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from api.analytics.fleet.compute_orchestration import wake_fleet_scope
from api.analytics.fleet.constants import ANALYTIC_ID as FLEET_ANALYTIC_ID
from api.analytics.fleet.fleet_table_stream_registry import reschedule_fleet_table_player
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.ledger_persisted_event import FleetLedgerPersistedEvent
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    get_inference_row_scheduler,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    reschedule_all_inference_rows,
    reschedule_inference_row,
)
from api.analytics.off_mode import MarkPersist, off_mode_persist_decision
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.compute.orchestrator import ComputeOrchestrator, OpenTurnRoot
from api.compute.orchestrator_state import ComputeNodeRun
from api.compute.runtime import peek_compute_orchestrator
from api.compute.scope import ComputeScope
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.streaming.table_stream.registry_catalog import active_table_stream_turns

_OPEN_TURN_ANALYTICS = frozenset({FLEET_ANALYTIC_ID, SCORES_ANALYTIC_ID})


def preferred_unconsumed_root_backfill(
    roots: tuple[OpenTurnRoot, ...],
    *,
    host_turn: int,
    preferred_analytic_id: str,
) -> bool | None:
    """Backfill choice of the unconsumed root at ``host_turn``.

    None when no such root exists. ``preferred_analytic_id`` wins when more
    than one analytic has an unconsumed root at that turn. When it does not,
    the last other root in scan order supplies the choice.
    """
    found: bool | None = None
    for root in roots:
        if root.consumed or root.open_turn != host_turn:
            continue
        if root.analytic_id == preferred_analytic_id:
            return root.backfill_earlier_turns
        found = root.backfill_earlier_turns
    return found


def _carried_scores_backfill(
    roots: tuple[OpenTurnRoot, ...],
    *,
    host_turn: int,
) -> bool | None:
    """Backfill choice carried by the unconsumed root at ``host_turn``.

    None when no such root exists. A scores root wins over a fleet root.
    """
    return preferred_unconsumed_root_backfill(
        roots,
        host_turn=host_turn,
        preferred_analytic_id=SCORES_ANALYTIC_ID,
    )


def _player_submission_roots(
    orchestrator: ComputeOrchestrator | None,
    game_id: int,
    perspective: int,
    player_id: int,
    *,
    turn: int | None = None,
) -> tuple[OpenTurnRoot, ...]:
    """In-flight fleet and scores submission roots for one player."""
    if orchestrator is None:
        return ()
    return orchestrator.open_turn_roots(
        game_id=game_id,
        perspective=perspective,
        player_id=player_id,
        analytic_ids=_OPEN_TURN_ANALYTICS,
        turn=turn,
    )


def _claim_player_open_roots(
    *,
    game_id: int,
    perspective: int,
    player_id: int,
    open_turn: int,
    consume: Callable[[tuple[OpenTurnRoot, ...]], bool],
) -> tuple[OpenTurnRoot, ...]:
    """In-flight roots, consuming ``open_turn`` when ``consume`` says so.

    No orchestrator yields an empty snapshot. ``consume`` runs under the
    orchestrator lock and must not re-enter it. The snapshot is the state
    from before that consume.
    """
    orchestrator = peek_compute_orchestrator()
    if orchestrator is None:
        return ()
    return orchestrator.claim_open_turn_roots(
        game_id=game_id,
        perspective=perspective,
        player_id=player_id,
        open_turn=open_turn,
        analytic_ids=_OPEN_TURN_ANALYTICS,
        consume=consume,
    )


def discard_bumped_player_work(
    orchestrator: ComputeOrchestrator,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
    shell_turns: frozenset[int],
    live_turns: frozenset[int],
) -> None:
    """Drop in-flight fleet and scoreboard work that must not stamp a new mark.

    A shell turn, and any turn with a live table stream, is left alone when it
    is already executing so that work can still stamp. The same turn is failed
    when it has not started, so a fresh submit can recompute it. Every other
    in-flight turn for this player is dropped: a step that has not started
    fails now, and a step already executing finishes without persisting or
    stamping.

    The predicate runs under the orchestrator lock. It must not re-enter the
    orchestrator and reads node state only.
    """
    recompute_turns = set(live_turns)
    recompute_turns.update(shell_turns)

    def should_discard(scope: ComputeScope, node: ComputeNodeRun) -> bool:
        if scope.turn in recompute_turns:
            return node.state != "running"
        return True

    orchestrator.discard_matching_work(
        should_discard,
        game_id=game_id,
        perspective=perspective,
        player_id=player_id,
        analytic_ids=_OPEN_TURN_ANALYTICS,
    )


@dataclass(frozen=True)
class _LimitedRecompute:
    """Shell and live turns a durable bump recomputes while backfill is off.

    ``turns`` are those sets restricted to the evidence host turn and later.
    Discard uses the unfiltered sets: a shell or live turn before the evidence
    host turn is still in-flight work for this player.
    """

    turns: frozenset[int]
    shell_turns: frozenset[int]
    live_turns: frozenset[int]


@dataclass(frozen=True)
class _ChosenRecompute:
    """Recompute choice made while the submission root was still unconsumed.

    ``limited`` is None when every known turn wakes.
    """

    limited: _LimitedRecompute | None


def _limited_recompute_turns(
    *,
    host_turn: int,
    live_turns: frozenset[int],
    shell_turns: frozenset[int],
) -> _LimitedRecompute:
    """Turns to wake, plus the sets discard uses, for one durable bump."""
    turns = {turn for turn in live_turns if turn >= host_turn}
    turns.update(turn for turn in shell_turns if turn >= host_turn)
    return _LimitedRecompute(
        turns=frozenset(turns),
        shell_turns=shell_turns,
        live_turns=live_turns,
    )


@dataclass(frozen=True)
class _DurableScoresEvidence:
    """One durable scores persist, split by which backfill each step uses.

    Stamp versus bump uses the carried submission choice: ``decision_backfill``
    and ``open_turn``. Both are None when this host turn has no unconsumed
    root, and that persist cannot stamp.

    ``wake_backfill`` is the current backfill record. It chooses which turns
    wake after a bump or first persist. It does not classify the mark.

    ``chosen`` is the recompute snapshot taken from the claim, while that root
    was still unconsumed. None when ``open_turn`` is None; the wake then
    chooses turns itself.
    """

    open_turn: int | None
    decision_backfill: bool | None
    wake_backfill: bool
    chosen: _ChosenRecompute | None


def resolve_durable_scores_evidence(
    roots: tuple[OpenTurnRoot, ...],
    *,
    host_turn: int,
    wake_backfill: bool,
    live_turns: frozenset[int],
) -> _DurableScoresEvidence:
    """Carried submission choice and the current backfill record.

    ``open_turn`` is set exactly when ``_carried_scores_backfill`` finds an
    unconsumed root, which is also when that root is consumed. ``live_turns``
    is the pre-claim stream scan. It is unused when ``wake_backfill`` is on,
    because that setting wakes every known turn.
    """
    carried = _carried_scores_backfill(roots, host_turn=host_turn)
    if carried is None:
        return _DurableScoresEvidence(
            open_turn=None,
            decision_backfill=None,
            wake_backfill=wake_backfill,
            chosen=None,
        )
    if wake_backfill:
        chosen = _ChosenRecompute(limited=None)
    else:
        chosen = _ChosenRecompute(
            limited=_limited_recompute_turns(
                host_turn=host_turn,
                live_turns=live_turns,
                shell_turns=frozenset(root.open_turn for root in roots),
            )
        )
    return _DurableScoresEvidence(
        open_turn=host_turn,
        decision_backfill=carried,
        wake_backfill=wake_backfill,
        chosen=chosen,
    )


class InferenceInvalidationService:
    def __init__(
        self,
        persistence: InferenceRowPersistenceService,
        scheduler: InferenceRowScheduler | None = None,
        *,
        fleet_persistence: FleetSnapshotPersistenceService | None = None,
    ) -> None:
        self._persistence = persistence
        self._scheduler = scheduler
        self._fleet_persistence = fleet_persistence

    def _scheduler_instance(self) -> InferenceRowScheduler:
        if self._scheduler is not None:
            return self._scheduler
        return get_inference_row_scheduler()

    def _scope(self, game_id: int, perspective: int, host_turn: int) -> InferenceStreamScope:
        return InferenceStreamScope(
            game_id=game_id,
            perspective=perspective,
            turn_number=host_turn,
        )

    def on_turn_stored(self, game_id: int, perspective: int, turn_number: int) -> None:
        cleared_host_turns = self._persistence.invalidate_for_turn_write(
            game_id,
            perspective,
            turn_number,
        )
        for host_turn in cleared_host_turns:
            reschedule_all_inference_rows(self._scope(game_id, perspective, host_turn))

    def on_inference_evidence_updated(
        self,
        game_id: int,
        perspective: int,
        host_turn: int,
        player_id: int,
        *,
        durable: bool = False,
        backfill_earlier_turns: bool | None = None,
    ) -> set[int]:
        """Wake fleet after scores evidence changes, without rewriting ledger files.

        Held admission (``durable=False``) bumps the in-memory epoch so in-flight
        fleet work for this player aborts. A persisted scores row (``durable=True``)
        also bumps the player's evidence mark. Existing ledger files stay readable
        and are not ensure-final when the mark moves.

        Always wakes ``fleet@host_turn`` for this player. A prior fleet persist may
        have refused with open scores evidence (no ``put_ledger``); without this
        wake, scores re-close would never rematerialize that scope. Open fleet
        table streams reschedule in place; otherwise ``force_fresh`` submit
        replaces a terminal that is no longer ensure-final.
        """
        return self._update_fleet_after_evidence(
            game_id,
            perspective,
            host_turn,
            player_id,
            durable=durable,
            backfill_earlier_turns=backfill_earlier_turns,
            chosen=None,
        )

    def _update_fleet_after_evidence(
        self,
        game_id: int,
        perspective: int,
        host_turn: int,
        player_id: int,
        *,
        durable: bool,
        backfill_earlier_turns: bool | None,
        chosen: _ChosenRecompute | None,
    ) -> set[int]:
        """Invalidate, discard a limited bump, and wake fleet.

        ``chosen`` is the recompute decision when the caller already made it.
        None means this method chooses. A limited choice discards in-flight
        work that must not stamp the new mark; waking every known turn does not.
        """
        if self._fleet_persistence is None:
            return set()
        turns_to_reschedule = self._fleet_persistence.invalidate_player_ledgers_from_turn(
            game_id,
            perspective,
            host_turn,
            player_id,
            durable=durable,
        )
        limited = (
            chosen.limited
            if chosen is not None
            else self._recompute_turns_after_evidence(
                game_id,
                perspective,
                player_id,
                host_turn,
                durable=durable,
                backfill_earlier_turns=backfill_earlier_turns,
            )
        )
        if limited is not None:
            orchestrator = peek_compute_orchestrator()
            if orchestrator is not None:
                discard_bumped_player_work(
                    orchestrator,
                    game_id=game_id,
                    perspective=perspective,
                    player_id=player_id,
                    shell_turns=limited.shell_turns,
                    live_turns=limited.live_turns,
                )
        turns_to_wake = turns_to_reschedule if limited is None else limited.turns
        live_scores_turns = (
            self._live_scores_turns(game_id, perspective) if limited is not None else frozenset()
        )
        for fleet_turn in sorted(turns_to_wake):
            stream_woke = reschedule_fleet_table_player(
                FleetTableStreamScope(
                    game_id=game_id,
                    perspective=perspective,
                    turn_number=fleet_turn,
                ),
                player_id,
            )
            if limited is not None and fleet_turn in live_scores_turns:
                reschedule_inference_row(self._scope(game_id, perspective, fleet_turn), player_id)
            if stream_woke:
                continue
            wake_fleet_scope(
                ComputeScope(
                    analytic_id=FLEET_ANALYTIC_ID,
                    game_id=game_id,
                    perspective=perspective,
                    turn=fleet_turn,
                    player_id=player_id,
                )
            )
        return turns_to_reschedule

    def _live_scores_turns(self, game_id: int, perspective: int) -> frozenset[int]:
        return active_table_stream_turns(game_id, perspective, (SCORES_ANALYTIC_ID,))

    def _recompute_turns_after_evidence(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        host_turn: int,
        *,
        durable: bool,
        backfill_earlier_turns: bool | None = None,
    ) -> _LimitedRecompute | None:
        """Turns to wake after a durable bump while backfill is off.

        None means the existing wake-every-known-turn rule. A durable bump with
        the setting off recomputes the shell and later turns that already have
        a live table stream, and leaves every other later turn on disk.
        ``backfill_earlier_turns`` is the current setting when the caller
        already read it for this event.
        """
        if not durable or self._fleet_persistence is None:
            return None
        enabled = (
            backfill_earlier_turns
            if backfill_earlier_turns is not None
            else self._fleet_persistence.backfill_earlier_turns_enabled(game_id)
        )
        if enabled:
            return None
        live_turns = active_table_stream_turns(
            game_id,
            perspective,
            _OPEN_TURN_ANALYTICS,
        )
        # Shell turns are the roots of in-flight fleet and scores submissions.
        # A live table stream is not itself an open: turn 41 streaming while
        # the user opened 40 stays a later turn. A consumed root stays a shell.
        shell_turns = frozenset(
            root.open_turn
            for root in _player_submission_roots(
                peek_compute_orchestrator(),
                game_id,
                perspective,
                player_id,
            )
        )
        return _limited_recompute_turns(
            host_turn=host_turn,
            live_turns=live_turns,
            shell_turns=shell_turns,
        )

    def wire_fleet_invalidation_to_persistence(self) -> None:
        """Register fleet snapshot invalidation on inference row persistence writes."""
        if self._fleet_persistence is None:
            self._persistence.on_row_persisted = None
            return
        self._persistence.on_row_persisted = self.on_scores_row_persisted

    def wire_scores_invalidation_to_fleet_persistence(self) -> None:
        """Register per-player scores row invalidation on fleet ledger persist callbacks."""
        if self._fleet_persistence is None:
            return
        self._fleet_persistence.on_snapshot_persisted = None
        self._fleet_persistence.on_ledger_persisted = self.on_fleet_ledger_persisted

    def on_scores_row_persisted(
        self,
        game_id: int,
        perspective: int,
        host_turn: int,
        player_id: int,
    ) -> None:
        """Durable scores evidence.

        Classify with ``off_mode_persist_decision``, then stamp or wake.
        A stamp leaves the mark unchanged. First persist and bump both advance
        it: an absent mark becomes generation 1, and an existing mark increments.
        Ledger files stay in place.

        ``_DurableScoresEvidence`` holds the split between those steps. The
        carried submission choice classifies stamp versus bump. The current
        backfill record chooses which turns wake. An unconsumed root at this
        host turn is consumed under one orchestrator lock. A bump that had
        that root wakes from the recompute snapshot taken with the claim. A
        host turn with no unconsumed root does not consume, and the wake
        chooses turns after the claim.
        """

        def consume_root(roots: tuple[OpenTurnRoot, ...]) -> bool:
            return _carried_scores_backfill(roots, host_turn=host_turn) is not None

        fleet = self._fleet_persistence
        if fleet is None:
            # No fleet service: no mark to classify and no fleet to wake.
            # An unconsumed root is still consumed so the one-shot cannot apply again.
            _claim_player_open_roots(
                game_id=game_id,
                perspective=perspective,
                player_id=player_id,
                open_turn=host_turn,
                consume=consume_root,
            )
            return

        wake_backfill = fleet.backfill_earlier_turns_enabled(game_id)
        mark = fleet.evidence_mark(game_id, perspective, player_id)
        # Live turns are read before the claim. The claim callback must not
        # re-enter the orchestrator, and a stream scan takes its own locks.
        live_turns = (
            active_table_stream_turns(game_id, perspective, _OPEN_TURN_ANALYTICS)
            if not wake_backfill
            else frozenset()
        )
        roots = _claim_player_open_roots(
            game_id=game_id,
            perspective=perspective,
            player_id=player_id,
            open_turn=host_turn,
            consume=consume_root,
        )
        evidence = resolve_durable_scores_evidence(
            roots,
            host_turn=host_turn,
            wake_backfill=wake_backfill,
            live_turns=live_turns,
        )
        # The carried choice classifies the mark. Catch-up and the stored
        # generation stay unset; they do not change this classification.
        # An absent carried choice leaves the open turn unset, so this cannot stamp.
        carried = evidence.decision_backfill
        decision = off_mode_persist_decision(
            backfill_enabled=False if carried is None else carried,
            open_turn=evidence.open_turn,
            is_catch_up=False,
            host_turn=host_turn,
            mark=mark,
            stored_generation=None,
        )
        if decision.mark_persist is MarkPersist.STAMP:
            return
        if evidence.chosen is None:
            self.on_inference_evidence_updated(
                game_id,
                perspective,
                host_turn,
                player_id,
                durable=True,
                backfill_earlier_turns=evidence.wake_backfill,
            )
            return
        self._update_fleet_after_evidence(
            game_id,
            perspective,
            host_turn,
            player_id,
            durable=True,
            backfill_earlier_turns=evidence.wake_backfill,
            chosen=evidence.chosen,
        )

    def on_fleet_ledger_persisted(self, event: FleetLedgerPersistedEvent) -> None:
        """Drop one player's scores@N inference row when fleet@(N-1) is persisted.

        Own-DAG elision (#204): when scores is already a non-terminal dependent of
        that fleet scope on the same orchestrator DAG, skip wipe and reschedule.
        """
        host_turn = event.fleet_turn + 1
        scope = self._scope(event.game_id, event.perspective, host_turn)
        scheduler = self._scheduler_instance()
        should_reschedule = scheduler.should_reschedule_scores_row_after_fleet_persist(
            scope,
            event,
            invalidate_row=lambda: self._persistence.delete_row(
                event.game_id,
                event.perspective,
                host_turn,
                event.player_id,
            ),
        )
        if not should_reschedule:
            return
        reschedule_inference_row(scope, event.player_id)

    def on_fleet_snapshot_persisted(
        self,
        game_id: int,
        perspective: int,
        fleet_turn: int,
    ) -> None:
        """Legacy roster-level invalidation after explicit ``put_snapshot`` only.

        Production scores coupling uses ``on_fleet_ledger_persisted`` per player.
        """
        host_turn = fleet_turn + 1
        self._persistence.delete_host_turn_document(game_id, perspective, host_turn)
        reschedule_all_inference_rows(
            self._scope(game_id, perspective, host_turn),
            force_schedule=True,
        )

    def bind_scheduler(self, scheduler: InferenceRowScheduler) -> None:
        self._scheduler = scheduler

    def on_hull_mask_changed(
        self,
        game_id: int,
        perspective: int,
        host_turn: int,
        player_id: int,
    ) -> None:
        self._persistence.delete_row(game_id, perspective, host_turn, player_id)
        self.on_inference_evidence_updated(
            game_id,
            perspective,
            host_turn,
            player_id,
            durable=True,
        )
        reschedule_inference_row(
            self._scope(game_id, perspective, host_turn),
            player_id,
        )

    def recompute_host_turn(
        self,
        game_id: int,
        perspective: int,
        host_turn: int,
    ) -> None:
        self._persistence.delete_host_turn_document(game_id, perspective, host_turn)
        if self._fleet_persistence is not None:
            self._fleet_persistence.invalidate_for_turn_write(
                game_id,
                perspective,
                host_turn,
            )
        scope = self._scope(game_id, perspective, host_turn)
        scheduler = self._scheduler_instance()
        scheduler.clear_global_pause_for_scope(scope)
        reschedule_all_inference_rows(scope, force_schedule=True)

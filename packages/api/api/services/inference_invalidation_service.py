"""Coordinate scores inference persistence invalidation and in-place stream reschedule."""

from __future__ import annotations

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
        if self._fleet_persistence is None:
            return set()
        turns_to_reschedule = self._fleet_persistence.invalidate_player_ledgers_from_turn(
            game_id,
            perspective,
            host_turn,
            player_id,
            durable=durable,
        )
        recompute_turns = self._recompute_turns_after_evidence(
            game_id,
            perspective,
            player_id,
            host_turn,
            durable=durable,
            backfill_earlier_turns=backfill_earlier_turns,
        )
        if recompute_turns is None:
            turns_to_wake = turns_to_reschedule
        else:
            turns_to_wake = recompute_turns
        for fleet_turn in sorted(turns_to_wake):
            stream_woke = reschedule_fleet_table_player(
                FleetTableStreamScope(
                    game_id=game_id,
                    perspective=perspective,
                    turn_number=fleet_turn,
                ),
                player_id,
            )
            if (
                recompute_turns is not None
                and fleet_turn in recompute_turns
                and fleet_turn in self._live_scores_turns(game_id, perspective)
            ):
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
    ) -> set[int] | None:
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
        orchestrator = peek_compute_orchestrator()
        # Shell turns are the roots of in-flight fleet and scores submissions.
        # A live table stream is not itself an open: turn 41 streaming while
        # the user opened 40 stays a later turn.
        shell_turns = frozenset(
            root.open_turn
            for root in _player_submission_roots(
                orchestrator,
                game_id,
                perspective,
                player_id,
            )
        )
        recompute = {turn for turn in live_turns if turn >= host_turn}
        recompute.update(turn for turn in shell_turns if turn >= host_turn)
        if orchestrator is not None:
            discard_bumped_player_work(
                orchestrator,
                game_id=game_id,
                perspective=perspective,
                player_id=player_id,
                shell_turns=shell_turns,
                live_turns=live_turns,
            )
        return recompute

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

        ``off_mode_persist_decision`` classifies this persist. A stamp leaves
        the mark unchanged. First persist and bump both advance it through
        durable evidence update: an absent mark becomes generation 1, and an
        existing mark increments. Ledger files stay in place. The matching
        in-flight submission root is consumed either way, after a bump has
        already chosen which turns to recompute.
        """
        open_turn = self._unconsumed_submission_open(game_id, perspective, player_id, host_turn)
        carried = self._carried_submission_backfill(game_id, perspective, player_id, host_turn)
        current: bool | None = None
        if carried is None and self._fleet_persistence is not None:
            current = self._fleet_persistence.backfill_earlier_turns_enabled(game_id)
        if self._fleet_persistence is not None:
            # This call classifies the mark. It is not a fleet merge, so the
            # catch-up flag is false and the stored generation is unused.
            # An in-flight submission keeps the choice it started with. A
            # persist with no such submission uses the current record, read
            # once for this event.
            decision_backfill = current if carried is None else carried
            decision = off_mode_persist_decision(
                backfill_enabled=decision_backfill if decision_backfill is not None else False,
                open_turn=open_turn,
                is_catch_up=False,
                host_turn=host_turn,
                mark=self._fleet_persistence.evidence_mark(game_id, perspective, player_id),
                stored_generation=None,
            )
            if decision.mark_persist is MarkPersist.STAMP:
                self._consume_submission_open(game_id, perspective, player_id, host_turn)
                return
        if current is None and self._fleet_persistence is not None:
            current = self._fleet_persistence.backfill_earlier_turns_enabled(game_id)
        self.on_inference_evidence_updated(
            game_id,
            perspective,
            host_turn,
            player_id,
            durable=True,
            backfill_earlier_turns=current,
        )
        if open_turn is not None and host_turn == open_turn:
            self._consume_submission_open(game_id, perspective, player_id, host_turn)

    def _unconsumed_submission_open(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        host_turn: int,
    ) -> int | None:
        """The in-flight submission root when this host turn is that root and still one-shot."""
        roots = _player_submission_roots(
            peek_compute_orchestrator(),
            game_id,
            perspective,
            player_id,
            turn=host_turn,
        )
        if any(not root.consumed for root in roots):
            return host_turn
        return None

    def _carried_submission_backfill(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        host_turn: int,
    ) -> bool | None:
        """Setting the in-flight submission started with, when this turn is that root.

        A scores root wins when more than one analytic has an unconsumed root
        at this turn.
        """
        roots = _player_submission_roots(
            peek_compute_orchestrator(),
            game_id,
            perspective,
            player_id,
            turn=host_turn,
        )
        return preferred_unconsumed_root_backfill(
            roots,
            host_turn=host_turn,
            preferred_analytic_id=SCORES_ANALYTIC_ID,
        )

    def _consume_submission_open(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        open_turn: int,
    ) -> None:
        orchestrator = peek_compute_orchestrator()
        if orchestrator is None:
            return
        orchestrator.consume_open_turn_roots(
            game_id=game_id,
            perspective=perspective,
            player_id=player_id,
            open_turn=open_turn,
            analytic_ids=_OPEN_TURN_ANALYTICS,
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

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
from api.analytics.off_mode import MarkPersist, off_mode_mark_persist
from api.analytics.on_walk import scoreboard_persist_belongs_to_on_walk
from api.compute.orchestrator import ComputeOrchestrator
from api.compute.scope import ComputeScope
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.services.off_mode_bump import (
    DeferRecompute,
    InFlightOrchestrator,
    OrchestratorResolver,
    ResolvedRecompute,
    claim_player_open_roots,
    in_flight_orchestrator,
    live_turns_for_limited_recompute,
    recompute_decision_at_wake,
    resolve_durable_scores_evidence,
)


def _no_process_orchestrator() -> ComputeOrchestrator | None:
    """No orchestrator is wired, so none can be in flight."""
    return None


class InferenceInvalidationService:
    def __init__(
        self,
        persistence: InferenceRowPersistenceService,
        scheduler: InferenceRowScheduler | None = None,
        *,
        fleet_persistence: FleetSnapshotPersistenceService | None = None,
        orchestrator: OrchestratorResolver = _no_process_orchestrator,
    ) -> None:
        self._persistence = persistence
        self._scheduler = scheduler
        self._fleet_persistence = fleet_persistence
        self._resolve_orchestrator = orchestrator

    def _current_orchestrator(self) -> InFlightOrchestrator:
        """Process orchestrator for this persist, or a stand-in when none exists.

        The stand-in does not start a worker pool. It has no in-flight roots
        and nothing to discard.
        """
        return in_flight_orchestrator(self._resolve_orchestrator())

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

        The recompute is chosen while the player epoch is still the old one,
        from the current backfill record, roots, and one live-stream scan.
        Discard flags work that must not stamp, then the ledger bump advances
        the mark and the epoch. Fleet and scores wakes run after that bump.
        A limited recompute reschedules scores rows for woken turns that this
        scan recorded as scores. Held admission wakes every known turn and
        does not discard in-flight work.
        """
        fleet = self._fleet_persistence
        if fleet is None:
            return set()
        orchestrator = self._current_orchestrator()
        backfill_enabled = (
            backfill_earlier_turns
            if backfill_earlier_turns is not None
            else fleet.backfill_earlier_turns_enabled(game_id)
        )
        resolved = recompute_decision_at_wake(
            host_turn=host_turn,
            durable=durable,
            backfill_enabled=backfill_enabled,
            game_id=game_id,
            perspective=perspective,
            player_id=player_id,
            orchestrator=orchestrator,
        )
        return self._discard_bump_and_wake(
            fleet,
            game_id,
            perspective,
            host_turn,
            player_id,
            durable=durable,
            resolved=resolved,
            orchestrator=orchestrator,
        )

    def _discard_bump_and_wake(
        self,
        fleet: FleetSnapshotPersistenceService,
        game_id: int,
        perspective: int,
        host_turn: int,
        player_id: int,
        *,
        durable: bool,
        resolved: ResolvedRecompute,
        orchestrator: InFlightOrchestrator,
    ) -> set[int]:
        """Discard, then bump the mark and epoch, then wake.

        ``resolved`` was chosen while this player's epoch was still the old
        one. Discard flags work that must not stamp before
        ``invalidate_player_ledgers_from_turn`` publishes the new epoch, so
        epoch retry cannot rebuild that work onto the new generation. Fleet
        and scores wakes run after the bump, so replacement work observes the
        new mark. Wake-all discard leaves in-flight work running.
        """
        resolved.discard_bumped_work(
            orchestrator,
            game_id=game_id,
            perspective=perspective,
            player_id=player_id,
        )
        turns_to_reschedule = fleet.invalidate_player_ledgers_from_turn(
            game_id,
            perspective,
            host_turn,
            player_id,
            durable=durable,
        )
        self._wake_fleet_turns(
            game_id,
            perspective,
            player_id,
            resolved=resolved,
            turns_to_reschedule=turns_to_reschedule,
        )
        self._wake_scores_rows_for_recompute(
            game_id,
            perspective,
            player_id,
            resolved=resolved,
            turns_to_reschedule=turns_to_reschedule,
        )
        return turns_to_reschedule

    def _wake_fleet_turns(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        *,
        resolved: ResolvedRecompute,
        turns_to_reschedule: set[int],
    ) -> None:
        """Wake fleet for an already-resolved recompute after the epoch bump.

        ``turns_to_reschedule`` is the ledger bump's known turns. Wake-all
        uses that set. A limited recompute uses the turns it already chose.
        """
        for fleet_turn in sorted(resolved.turns_to_wake(turns_to_reschedule)):
            stream_woke = reschedule_fleet_table_player(
                FleetTableStreamScope(
                    game_id=game_id,
                    perspective=perspective,
                    turn_number=fleet_turn,
                ),
                player_id,
            )
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

    def _wake_scores_rows_for_recompute(
        self,
        game_id: int,
        perspective: int,
        player_id: int,
        *,
        resolved: ResolvedRecompute,
        turns_to_reschedule: set[int],
    ) -> None:
        """Reschedule scores rows for woken turns the recompute's scan recorded as scores."""
        for turn in sorted(resolved.live_scores_turns_to_wake(turns_to_reschedule)):
            reschedule_inference_row(self._scope(game_id, perspective, turn), player_id)

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

        Classify with ``off_mode_mark_persist``, then stamp or wake.
        A stamp leaves the mark unchanged. First persist and bump both advance
        it: an absent mark becomes generation 1, and an existing mark increments.
        Ledger files stay in place.

        ``DurableScoresEvidence`` holds the split between those steps. The
        carried submission choice classifies stamp versus bump. The current
        backfill record chooses which turns wake. An unconsumed root at this
        host turn is consumed under one orchestrator lock. A bump that had
        that root wakes from the recompute snapshot taken with the claim. A
        host turn with no unconsumed root does not consume. A stamp returns
        before any discard or bump. A deferred recompute reads current roots
        and live streams while the epoch is still the old one. Discard flags
        work that must not stamp, then the ledger bump advances the mark and
        the epoch, then fleet and scores wake. A limited recompute
        reschedules scores rows from the scan that chose it.
        """
        orchestrator = self._current_orchestrator()
        fleet = self._fleet_persistence
        if fleet is None:
            # No fleet service: no mark to classify and no fleet to wake.
            # An unconsumed root is still consumed so the one-shot cannot apply again.
            claim_player_open_roots(
                orchestrator,
                game_id=game_id,
                perspective=perspective,
                player_id=player_id,
                open_turn=host_turn,
            )
            return

        wake_backfill = fleet.backfill_earlier_turns_enabled(game_id)
        mark = fleet.evidence_mark(game_id, perspective, player_id)
        # One pre-claim scan, split by analytic id.
        live_turns_by_analytic = live_turns_for_limited_recompute(
            game_id,
            perspective,
            durable=True,
            backfill_enabled=wake_backfill,
        )
        roots = claim_player_open_roots(
            orchestrator,
            game_id=game_id,
            perspective=perspective,
            player_id=player_id,
            open_turn=host_turn,
        )
        evidence = resolve_durable_scores_evidence(
            roots,
            host_turn=host_turn,
            wake_backfill=wake_backfill,
            live_turns_by_analytic=live_turns_by_analytic,
        )
        # The carried choice classifies the mark. An absent carried choice
        # leaves the open turn unset, so the open-turn rule cannot stamp.
        # An in-flight on-walk stamps the generation it started with instead.
        carried = evidence.decision_backfill
        mark_persist = off_mode_mark_persist(
            on_walk=scoreboard_persist_belongs_to_on_walk(
                orchestrator,
                game_id=game_id,
                perspective=perspective,
                player_id=player_id,
                host_turn=host_turn,
            ),
            mark=mark,
            backfill_enabled=False if carried is None else carried,
            open_turn=evidence.open_turn,
            host_turn=host_turn,
        )
        if mark_persist is MarkPersist.STAMP:
            return
        recompute = evidence.recompute
        if isinstance(recompute, DeferRecompute):
            resolved = recompute_decision_at_wake(
                host_turn=host_turn,
                durable=True,
                backfill_enabled=evidence.wake_backfill,
                game_id=game_id,
                perspective=perspective,
                player_id=player_id,
                orchestrator=orchestrator,
            )
        else:
            resolved = recompute
        self._discard_bump_and_wake(
            fleet,
            game_id,
            perspective,
            host_turn,
            player_id,
            durable=True,
            resolved=resolved,
            orchestrator=orchestrator,
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
        scheduler.clear_global_pause_for_replaced_rows(scope)
        reschedule_all_inference_rows(scope, force_schedule=True)

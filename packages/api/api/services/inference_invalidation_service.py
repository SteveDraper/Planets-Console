"""Coordinate scores inference persistence invalidation and in-place stream reschedule."""

from __future__ import annotations

from api.analytics.fleet.compute_orchestration import wake_fleet_scope
from api.analytics.fleet.fleet_table_stream_registry import reschedule_fleet_table_player
from api.analytics.fleet.fleet_table_stream_scope import FleetTableStreamScope
from api.analytics.fleet.ledger_persisted_event import FleetLedgerPersistedEvent
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet_walk_analytics import FLEET_WALK_ANALYTIC_IDS
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
from api.analytics.walk_row_reschedule import reschedule_walk_rows
from api.callback_containment import FailureCollector
from api.compute.in_flight_settle import PlayerWork
from api.compute.orchestrator import ComputeOrchestrator
from api.compute.scope import ComputeScope
from api.services.evidence_bump import (
    BumpRecompute,
    DurableRecompute,
    FleetScopeWake,
    HeldRecompute,
    LiveRowWake,
    WakeTarget,
    claim_player_open_roots,
    player_live_walk_rows,
    resolve_durable_scores_evidence,
)
from api.services.in_flight_orchestrator import (
    InFlightOrchestrator,
    OrchestratorResolver,
    in_flight_orchestrator,
)
from api.services.inference_row_persistence_service import InferenceRowPersistenceService


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
        and nothing to settle.
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
        """Bump the player's fleet evidence after scores evidence changes, then wake.

        Existing ledger files stay readable and are not ensure-final when the
        mark moves.

        A durable bump (``durable=True``: a persisted scores row or a changed
        hull mask) follows :class:`DurableRecompute`. It settles the player's
        fleet and scoreboard work, advances the mark and the epoch in the same
        orchestrator lock hold, then reschedules the player's live rows at
        ``host_turn`` and later and each live row whose own root it stopped.
        ``backfill_earlier_turns`` overrides the stored setting for what it
        watches.

        Held admission (``durable=False``) follows :class:`HeldRecompute`: it
        bumps only the in-memory epoch, settles nothing, and wakes every known
        fleet turn of the player.

        Returns the ledger bump's known turns.
        """
        fleet = self._fleet_persistence
        if fleet is None:
            return set()
        recompute: BumpRecompute
        if durable:
            recompute = DurableRecompute(
                host_turn=host_turn,
                backfill_enabled=(
                    backfill_earlier_turns
                    if backfill_earlier_turns is not None
                    else fleet.backfill_earlier_turns_enabled(game_id)
                ),
            )
        else:
            recompute = HeldRecompute(game_id=game_id, perspective=perspective, player_id=player_id)
        return self._settle_bump_and_wake(
            fleet,
            game_id,
            perspective,
            host_turn,
            player_id,
            durable=durable,
            recompute=recompute,
        )

    def _settle_bump_and_wake(
        self,
        fleet: FleetSnapshotPersistenceService,
        game_id: int,
        perspective: int,
        host_turn: int,
        player_id: int,
        *,
        durable: bool,
        recompute: BumpRecompute,
    ) -> set[int]:
        """Settle, then bump the mark and the epoch in the same lock hold, then wake.

        The live rows that choose the settle policy are scanned first, with no
        lock. The ledger bump runs as the settle's ``then``, so no plan can
        register between the settle and the new mark and epoch. The rows to
        wake come from a second scan after that publish: a row that opened
        during the bump either planned against the new mark or had its work
        stopped by the settle. The bump runs in the same hold even when
        ``recompute`` settles nothing.

        The settle's queued abort listeners are drained before the wake, as
        the game stop drains before its reschedules. Outside a drain, each
        row's listeners have therefore run before the row is re-admitted. A
        durable bump runs inside a scores persist callback, where the drain
        call returns at once (the active drain runs the listeners after that
        callback), so there the wake re-admits rows before their abort
        listeners run.

        A mark write that raises an ``Exception`` is contained and logged; the
        stopped rows are still woken, then that error is raised as it was. An
        interrupt in the mark write propagates at once, without the wake.
        """
        orchestrator = self._current_orchestrator()
        known_turns: set[int] = set()
        bump_failures = FailureCollector()

        def bump_known_turns() -> None:
            known_turns.update(
                fleet.invalidate_player_ledgers_from_turn(
                    game_id,
                    perspective,
                    host_turn,
                    player_id,
                    durable=durable,
                )
            )

        def bump_mark_and_epoch() -> None:
            bump_failures.run(bump_known_turns, "Fleet ledger bump")

        policy = recompute.settle_policy(player_live_walk_rows(game_id, perspective, player_id))
        if policy is None:
            bump_mark_and_epoch()
            stopped: frozenset[ComputeScope] = frozenset()
        else:
            stopped = orchestrator.settle_in_flight_work(
                PlayerWork(
                    game_id=game_id,
                    perspective=perspective,
                    player_id=player_id,
                    analytic_ids=FLEET_WALK_ANALYTIC_IDS,
                ),
                policy,
                then=bump_mark_and_epoch,
            )
        orchestrator.drain_post_lock_callbacks()
        self._wake(
            recompute.wake_targets(
                known_turns=frozenset(known_turns),
                stopped=stopped,
                live_rows=player_live_walk_rows(game_id, perspective, player_id),
            )
        )
        if bump_failures.first_error is not None:
            raise bump_failures.first_error
        return known_turns

    def _wake(self, targets: tuple[WakeTarget, ...]) -> None:
        """Run each wake target.

        A live row reschedules through its own stream. A fleet scope
        reschedules its open stream's row, or else is submitted ``force_fresh``.
        """
        reschedule_walk_rows(target.row for target in targets if isinstance(target, LiveRowWake))
        for target in targets:
            if not isinstance(target, FleetScopeWake):
                continue
            scope = target.scope
            stream_woke = reschedule_fleet_table_player(
                FleetTableStreamScope(
                    game_id=scope.game_id,
                    perspective=scope.perspective,
                    turn_number=scope.turn,
                ),
                scope.player_id,
            )
            if not stream_woke:
                wake_fleet_scope(scope)

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
        *,
        on_walk: bool,
    ) -> None:
        """Durable scores evidence: stamp the mark, or bump it and wake.

        ``off_mode_mark_persist`` classifies. A stamp leaves the mark
        unchanged. First persist and bump both advance it: an absent mark
        becomes generation 1, and an existing mark increments. Ledger files
        stay in place.

        ``on_walk`` is the producing execution's walk membership, carried on
        its persist payload, so a persist whose node ended after the write was
        admitted still stamps for its walk. The live node is not read.

        The carried submission choice on an unconsumed root at this host turn
        classifies stamp versus bump, and that root is consumed under one
        orchestrator lock. A host turn with no unconsumed root does not
        consume. A bump then follows :class:`DurableRecompute` with the current
        backfill record (``on_inference_evidence_updated``).
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

        mark = fleet.evidence_mark(game_id, perspective, player_id)
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
            wake_backfill=fleet.backfill_earlier_turns_enabled(game_id),
        )
        # The carried choice classifies the mark. An absent carried choice
        # leaves the open turn unset, so the open-turn rule cannot stamp.
        # A persist produced on a walk stamps the generation it started with instead.
        carried = evidence.decision_backfill
        mark_persist = off_mode_mark_persist(
            on_walk=on_walk,
            mark=mark,
            backfill_enabled=False if carried is None else carried,
            open_turn=evidence.open_turn,
            host_turn=host_turn,
        )
        if mark_persist is MarkPersist.STAMP:
            return
        self.on_inference_evidence_updated(
            game_id,
            perspective,
            host_turn,
            player_id,
            durable=True,
            backfill_earlier_turns=evidence.wake_backfill,
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
        """Drop the player's scores row at ``host_turn`` and bump its fleet evidence.

        The bump's wake reschedules that row when it is live.
        """
        self._persistence.delete_row(game_id, perspective, host_turn, player_id)
        self.on_inference_evidence_updated(
            game_id,
            perspective,
            host_turn,
            player_id,
            durable=True,
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
        # Reschedule while still paused, so no cancelled row's tier_solve is
        # dispatched; then release pause, even when the reschedule raises.
        try:
            reschedule_all_inference_rows(scope, force_schedule=True)
        finally:
            scheduler.clear_global_pause_for_replaced_rows(scope)

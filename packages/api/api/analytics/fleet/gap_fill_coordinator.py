"""Singleflight coordinator for fleet gap-fill and forward scores/fleet unwind."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from api.analytics.export_context import AnalyticQueryContext, make_analytic_query_context
from api.analytics.export_types import ExportScope
from api.analytics.fleet.chain import (
    FleetMaterializationProgressCallback,
    _find_gap_start_turn_for_player,
    _FleetSnapshotInvalidated,
    _GapFillCoherence,
    _is_fleet_ledger_cache_hit,
    _materialize_fleet_ledger_chain_for_player,
    _run_materialize_on_active_coherence,
    active_gap_fill_coherence,
    emit_gap_fill_leg_progress,
    gap_fill_coherence_scope,
    gap_fill_progress_scope,
)
from api.analytics.fleet.compute_services import FleetComputeServices
from api.analytics.fleet.constants import (
    ANALYTIC_ID,
    GAP_FILL_MATERIALIZE_WAIT_TIMEOUT_SEC,
    GAP_FILL_MAX_RETRIES,
    GAP_FILL_TARGET_TURN_COLLECT_SEC,
)
from api.analytics.fleet.exports import ensure_fleet_export
from api.analytics.fleet.gap_fill_deferred_notifications import (
    complete_ledger_turn_numbers_for_player,
    emit_deferred_fleet_ledger_notifications,
)
from api.analytics.fleet.held_solutions import FleetInferenceMaterialization
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import PersistedFleetLedger
from api.analytics.options import TurnAnalyticsOptions
from api.errors import ConflictError, FleetMaterializationTimeoutError, NotFoundError
from api.models.game import TurnInfo

_CoordinatorKey = tuple[int, int, int, int]


def _merge_progress_callback(
    existing: FleetMaterializationProgressCallback | None,
    incoming: FleetMaterializationProgressCallback | None,
) -> FleetMaterializationProgressCallback | None:
    if incoming is None:
        return existing
    if existing is None:
        return incoming
    if existing is incoming:
        return existing

    def merged(
        persisted: PersistedFleetLedger,
        materialize_turn: int,
    ) -> None:
        existing(persisted, materialize_turn)
        incoming(persisted, materialize_turn)

    return merged


@dataclass
class _InflightMaterialization:
    target_turn: int
    generation: int
    load_turn: Callable[[int], TurnInfo | None]
    inference_materialization: FleetInferenceMaterialization | None
    query_context: AnalyticQueryContext | None
    on_progress: FleetMaterializationProgressCallback | None = None
    event: threading.Event = field(default_factory=threading.Event)
    result_ledger: PersistedFleetLedger | None = None
    error: BaseException | None = None
    leader_thread: threading.Thread | None = None


@dataclass(frozen=True)
class _InflightJoin:
    """Whether the caller should lead gap-fill or wait on an existing inflight cycle."""

    inflight: _InflightMaterialization
    is_leader: bool


class _InflightSlot:
    """Singleflight slot: join an inflight cycle or start a new leader unwind."""

    def __init__(self, inflight_condition: threading.Condition) -> None:
        self._inflight_condition = inflight_condition
        self._inflight: _InflightMaterialization | None = None

    @property
    def inflight(self) -> _InflightMaterialization | None:
        return self._inflight

    def join(
        self,
        turn_number: int,
        generation: int,
        *,
        load_turn: Callable[[int], TurnInfo | None],
        inference_materialization: FleetInferenceMaterialization | None,
        query_context: AnalyticQueryContext | None,
        on_progress: FleetMaterializationProgressCallback | None = None,
    ) -> _InflightJoin:
        self._reap_abandoned()
        self._discard_stale_completed(turn_number, generation)
        existing = self._inflight
        if existing is not None and existing.generation == generation:
            return self._join_existing(existing, turn_number, on_progress=on_progress)
        return self._start_new(
            turn_number,
            generation,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
            query_context=query_context,
            on_progress=on_progress,
        )

    def _reap_abandoned(self) -> None:
        inflight = self._inflight
        if inflight is None or inflight.event.is_set():
            return
        leader_thread = inflight.leader_thread
        if leader_thread is not None and leader_thread.is_alive():
            return
        self._inflight = None
        inflight.event.set()

    def _discard_stale_completed(self, turn_number: int, generation: int) -> None:
        inflight = self._inflight
        if inflight is None or not inflight.event.is_set():
            return
        if inflight.generation != generation or turn_number <= inflight.target_turn:
            self._inflight = None

    def _join_existing(
        self,
        inflight: _InflightMaterialization,
        turn_number: int,
        *,
        on_progress: FleetMaterializationProgressCallback | None = None,
    ) -> _InflightJoin:
        if on_progress is not None:
            inflight.on_progress = _merge_progress_callback(inflight.on_progress, on_progress)
        extended = turn_number > inflight.target_turn
        previous_target = inflight.target_turn
        inflight.target_turn = max(inflight.target_turn, turn_number)
        if inflight.target_turn > previous_target:
            self._inflight_condition.notify_all()
        if inflight.event.is_set() and inflight.error is None and extended:
            inflight.event.clear()
            inflight.result_ledger = None
            inflight.leader_thread = threading.current_thread()
            return _InflightJoin(inflight=inflight, is_leader=True)
        return _InflightJoin(inflight=inflight, is_leader=False)

    def _start_new(
        self,
        turn_number: int,
        generation: int,
        *,
        load_turn: Callable[[int], TurnInfo | None],
        inference_materialization: FleetInferenceMaterialization | None,
        query_context: AnalyticQueryContext | None,
        on_progress: FleetMaterializationProgressCallback | None = None,
    ) -> _InflightJoin:
        inflight = _InflightMaterialization(
            target_turn=turn_number,
            generation=generation,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
            query_context=query_context,
            on_progress=on_progress,
            leader_thread=threading.current_thread(),
        )
        self._inflight = inflight
        return _InflightJoin(inflight=inflight, is_leader=True)


class FleetGapFillCoordinator:
    """At most one active gap-fill unwind per ``(persistence, game_id, perspective, player_id)``."""

    def __init__(
        self,
        persistence: FleetSnapshotPersistenceService,
        game_id: int,
        perspective: int,
        player_id: int,
    ) -> None:
        self._persistence = persistence
        self._game_id = game_id
        self._perspective = perspective
        self._player_id = player_id
        self._inflight_condition = threading.Condition()
        self._inflight_slot = _InflightSlot(self._inflight_condition)

    @property
    def epoch(self) -> int:
        """Current invalidation generation for this player scope."""
        return self._persistence.invalidation_generation(
            self._game_id,
            self._perspective,
            self._player_id,
        )

    def materialize_ledger(
        self,
        turn: TurnInfo,
        *,
        load_turn: Callable[[int], TurnInfo | None],
        inference_materialization: FleetInferenceMaterialization | None = None,
        query_context: AnalyticQueryContext | None = None,
        on_progress: FleetMaterializationProgressCallback | None = None,
    ) -> PersistedFleetLedger:
        turn_number = turn.settings.turn
        cached = self._persistence.get_ledger(
            self._game_id,
            self._perspective,
            turn_number,
            self._player_id,
        )
        if cached is not None and _is_fleet_ledger_cache_hit(cached):
            return cached

        if active_gap_fill_coherence() is not None:
            result = _run_materialize_on_active_coherence(
                self._persistence,
                self._game_id,
                self._perspective,
                turn,
                load_turn=load_turn,
                inference_materialization=inference_materialization,
                materialize_player_id=self._player_id,
            )
            assert isinstance(result, PersistedFleetLedger)
            return result

        return self._coordinate(
            turn,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
            query_context=query_context,
            on_progress=on_progress,
        )

    def _coordinate(
        self,
        turn: TurnInfo,
        *,
        load_turn: Callable[[int], TurnInfo | None],
        inference_materialization: FleetInferenceMaterialization | None,
        query_context: AnalyticQueryContext | None,
        on_progress: FleetMaterializationProgressCallback | None,
    ) -> PersistedFleetLedger:
        turn_number = turn.settings.turn
        with self._inflight_condition:
            join = self._inflight_slot.join(
                turn_number,
                self.epoch,
                load_turn=load_turn,
                inference_materialization=inference_materialization,
                query_context=query_context,
                on_progress=on_progress,
            )
        inflight = join.inflight

        if not join.is_leader:
            self._wait_for_inflight(inflight, turn_number)
            return self._result_for_request(inflight, turn_number, turn)

        try:
            self._run_leader_unwind(
                inflight,
                turn,
                load_turn=load_turn,
                inference_materialization=inference_materialization,
                query_context=query_context,
            )
        except BaseException as exc:
            inflight.error = exc
            raise
        finally:
            inflight.event.set()

        if inflight.error is not None:
            raise inflight.error
        return self._result_for_request(inflight, turn_number, turn)

    def _collect_target_turn_extensions(
        self,
        inflight: _InflightMaterialization,
    ) -> None:
        """Wait until concurrent waiters stop raising ``target_turn``.

        Waiters bump ``target_turn`` under ``_inflight_condition`` and notify the
        leader; the leader waits here (without holding the lock through unwind)
        until ``target_turn`` is unchanged for ``GAP_FILL_TARGET_TURN_COLLECT_SEC``.
        """
        settle_deadline = time.monotonic() + GAP_FILL_TARGET_TURN_COLLECT_SEC
        last_target = inflight.target_turn
        with self._inflight_condition:
            while True:
                now = time.monotonic()
                if now >= settle_deadline:
                    return
                if self._inflight_slot.inflight is not inflight:
                    return

                current_target = inflight.target_turn
                if current_target > last_target:
                    last_target = current_target
                    settle_deadline = now + GAP_FILL_TARGET_TURN_COLLECT_SEC

                remaining = settle_deadline - now
                if remaining <= 0:
                    return
                self._inflight_condition.wait(timeout=remaining)

    def _wait_for_inflight(
        self,
        inflight: _InflightMaterialization,
        turn_number: int,
    ) -> None:
        if not inflight.event.wait(timeout=GAP_FILL_MATERIALIZE_WAIT_TIMEOUT_SEC):
            raise FleetMaterializationTimeoutError(
                "fleet gap-fill for game "
                f"{self._game_id} perspective {self._perspective} "
                f"player {self._player_id} turn {turn_number} "
                f"did not complete within {GAP_FILL_MATERIALIZE_WAIT_TIMEOUT_SEC}s"
            )
        if inflight.error is not None:
            return
        cached = self._persistence.get_ledger(
            self._game_id,
            self._perspective,
            turn_number,
            self._player_id,
        )
        if cached is not None:
            return
        if inflight.generation != self.epoch:
            return
        raise FleetMaterializationTimeoutError(
            "fleet gap-fill waiter for game "
            f"{self._game_id} perspective {self._perspective} "
            f"player {self._player_id} turn {turn_number} "
            "completed without satisfying the requested ledger"
        )

    def _result_for_request(
        self,
        inflight: _InflightMaterialization,
        turn_number: int,
        turn: TurnInfo,
    ) -> PersistedFleetLedger:
        if inflight.error is not None:
            raise inflight.error
        if inflight.result_ledger is not None:
            return inflight.result_ledger
        cached = self._persistence.get_ledger(
            self._game_id,
            self._perspective,
            turn_number,
            self._player_id,
        )
        # Post-completion: return any ledger the cycle wrote for this turn, including
        # non-final provenance. ``materialize_ledger`` entry still requires ``is_final``
        # so partials rematerialize; requiring final here races with Phase C (scores
        # turn-evidence closed only when terminal) when ``result_ledger`` is cleared by
        # an extended re-lead before waiters read it.
        if cached is not None and turn_number <= inflight.target_turn:
            return cached

        if inflight.generation != self.epoch:
            return self._retry_after_epoch_bump(inflight, turn)

        raise ConflictError(
            f"fleet gap-fill for game {self._game_id} perspective {self._perspective} "
            f"player {self._player_id} turn {turn_number} completed without a cache hit"
        )

    def _retry_after_epoch_bump(
        self,
        inflight: _InflightMaterialization,
        turn: TurnInfo,
    ) -> PersistedFleetLedger:
        return self.materialize_ledger(
            turn,
            load_turn=inflight.load_turn,
            inference_materialization=inflight.inference_materialization,
            query_context=inflight.query_context,
            on_progress=inflight.on_progress,
        )

    def _run_leader_unwind(
        self,
        inflight: _InflightMaterialization,
        turn: TurnInfo,
        *,
        load_turn: Callable[[int], TurnInfo | None],
        inference_materialization: FleetInferenceMaterialization | None,
        query_context: AnalyticQueryContext | None,
    ) -> None:
        with gap_fill_progress_scope(lambda: inflight.on_progress):
            self._run_leader_unwind_body(
                inflight,
                turn,
                load_turn=load_turn,
                inference_materialization=inference_materialization,
                query_context=query_context,
            )

    def _run_leader_unwind_body(
        self,
        inflight: _InflightMaterialization,
        turn: TurnInfo,
        *,
        load_turn: Callable[[int], TurnInfo | None],
        inference_materialization: FleetInferenceMaterialization | None,
        query_context: AnalyticQueryContext | None,
    ) -> None:
        complete_before: frozenset[int] | None = None
        query_ctx = _resolve_query_context(
            self._persistence,
            self._game_id,
            self._perspective,
            turn,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
            query_context=query_context,
        )

        while True:
            self._collect_target_turn_extensions(inflight)
            target_turn = inflight.target_turn
            if complete_before is None:
                complete_before = complete_ledger_turn_numbers_for_player(
                    self._persistence,
                    self._game_id,
                    self._perspective,
                    self._player_id,
                    target_turn,
                    load_turn,
                )

            materialized_target: int | None = None
            for attempt in range(GAP_FILL_MAX_RETRIES):
                current_target = inflight.target_turn
                generation = self.epoch
                inflight.generation = generation
                coherence = _GapFillCoherence(
                    self._persistence,
                    self._game_id,
                    self._perspective,
                    self._player_id,
                    generation,
                )
                try:
                    with gap_fill_coherence_scope(coherence):
                        gap_start = _find_gap_start_turn_for_player(
                            self._persistence,
                            self._game_id,
                            self._perspective,
                            self._player_id,
                            current_target,
                            load_turn,
                        )
                        if gap_start <= current_target:
                            if inference_materialization is not None and query_ctx is None:
                                raise ConflictError(
                                    "fleet gap-fill requires query context when "
                                    "inference materialization is configured for "
                                    f"game {self._game_id} perspective "
                                    f"{self._perspective} player {self._player_id}"
                                )

                            materialized_via_export = False
                            if _can_forward_unwind_via_export(
                                query_ctx,
                                inference_materialization,
                            ):
                                materialized_via_export = self._forward_unwind_via_export_ensure(
                                    query_ctx,
                                    gap_start,
                                    current_target,
                                    load_turn,
                                    inference_materialization=inference_materialization,
                                )

                            if not materialized_via_export:
                                target_turn_info = load_turn(current_target)
                                if target_turn_info is None:
                                    if current_target == turn.settings.turn:
                                        target_turn_info = turn
                                    else:
                                        raise NotFoundError(
                                            f"fleet gap-fill requires stored turn "
                                            f"{current_target} for game {self._game_id} "
                                            f"perspective {self._perspective} "
                                            f"player {self._player_id}"
                                        )
                                from api.analytics.fleet.turn_context import FleetTurnContext

                                turn_context_cache: dict[int, FleetTurnContext] = {}
                                _materialize_fleet_ledger_chain_for_player(
                                    self._persistence,
                                    self._game_id,
                                    self._perspective,
                                    self._player_id,
                                    target_turn_info,
                                    load_turn=load_turn,
                                    inference_materialization=inference_materialization,
                                    coherence=coherence,
                                    turn_context_cache=turn_context_cache,
                                )
                    materialized_target = current_target
                    break
                except _FleetSnapshotInvalidated:
                    cached = self._persistence.get_ledger(
                        self._game_id,
                        self._perspective,
                        current_target,
                        self._player_id,
                    )
                    if cached is not None and _is_fleet_ledger_cache_hit(cached):
                        inflight.result_ledger = cached
                        return
                    if attempt + 1 >= GAP_FILL_MAX_RETRIES:
                        raise ConflictError(
                            f"fleet gap-fill for game {self._game_id} "
                            f"perspective {self._perspective} "
                            f"player {self._player_id} turn {inflight.target_turn} "
                            f"exceeded {GAP_FILL_MAX_RETRIES} invalidation retries"
                        ) from None
                    continue
            if materialized_target is None:
                raise ConflictError(
                    f"fleet gap-fill for game {self._game_id} perspective {self._perspective} "
                    f"player {self._player_id} turn {inflight.target_turn} exceeded "
                    f"{GAP_FILL_MAX_RETRIES} invalidation retries"
                )

            if inflight.target_turn > materialized_target:
                continue

            assert complete_before is not None
            emit_deferred_fleet_ledger_notifications(
                self._persistence,
                self._game_id,
                self._perspective,
                self._player_id,
                complete_before=complete_before,
                through_turn=materialized_target,
                load_turn=load_turn,
            )

            final_target = materialized_target
            target_turn_info = load_turn(final_target)
            if target_turn_info is None:
                if final_target == turn.settings.turn:
                    target_turn_info = turn
                else:
                    raise NotFoundError(
                        f"fleet gap-fill requires stored turn {final_target} "
                        f"for game {self._game_id} perspective {self._perspective} "
                        f"player {self._player_id}"
                    )
            persisted = self._persistence.get_ledger(
                self._game_id,
                self._perspective,
                final_target,
                self._player_id,
            )
            if persisted is None:
                raise ConflictError(
                    f"fleet ledger gap-fill produced no ledger "
                    f"for game {self._game_id} perspective {self._perspective} "
                    f"player {self._player_id} turn {final_target}"
                )
            inflight.result_ledger = persisted
            return

    def _forward_unwind_via_export_ensure(
        self,
        query_ctx: AnalyticQueryContext,
        gap_start: int,
        target_turn: int,
        load_turn: Callable[[int], TurnInfo | None],
        *,
        inference_materialization: FleetInferenceMaterialization | None,
    ) -> bool:
        """Return True when every gap turn has ensure-final ledger for this player."""
        player_id = self._player_id
        all_gap_turns_final = True

        for materialize_turn in range(gap_start, target_turn + 1):
            turn_info = load_turn(materialize_turn)
            if turn_info is None:
                raise NotFoundError(
                    f"fleet forward unwind requires stored turn {materialize_turn} "
                    f"for game {self._game_id} perspective {self._perspective} "
                    f"player {player_id}"
                )
            scope = ExportScope(
                game_id=self._game_id,
                perspective=self._perspective,
                turn=materialize_turn,
                player_id=player_id,
            )
            ensure_fleet_export(query_ctx, scope)

            persisted = self._persistence.get_ledger(
                self._game_id,
                self._perspective,
                materialize_turn,
                player_id,
            )
            materialized_via_chain = False
            if persisted is None or not _is_fleet_ledger_cache_hit(persisted):
                _run_materialize_on_active_coherence(
                    self._persistence,
                    self._game_id,
                    self._perspective,
                    turn_info,
                    load_turn=load_turn,
                    inference_materialization=inference_materialization,
                    materialize_player_id=player_id,
                )
                materialized_via_chain = True

            persisted = self._persistence.get_ledger(
                self._game_id,
                self._perspective,
                materialize_turn,
                player_id,
            )
            if persisted is not None and not materialized_via_chain:
                emit_gap_fill_leg_progress(persisted, materialize_turn)

            if not self._persistence.has_final_ledger(
                self._game_id,
                self._perspective,
                materialize_turn,
                player_id,
            ):
                all_gap_turns_final = False
        return all_gap_turns_final


_registry_lock = threading.Lock()
_coordinators: dict[_CoordinatorKey, FleetGapFillCoordinator] = {}


def coordinator_for(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    player_id: int,
) -> FleetGapFillCoordinator:
    key = (id(persistence), game_id, perspective, player_id)
    with _registry_lock:
        coordinator = _coordinators.get(key)
        if coordinator is None:
            coordinator = FleetGapFillCoordinator(
                persistence,
                game_id,
                perspective,
                player_id,
            )
            _coordinators[key] = coordinator
        return coordinator


def reset_coordinators() -> None:
    """Clear the process-wide coordinator registry (tests only)."""
    with _registry_lock:
        _coordinators.clear()


def _can_forward_unwind_via_export(
    query_ctx: AnalyticQueryContext | None,
    inference_materialization: FleetInferenceMaterialization | None,
) -> bool:
    """Forward export ensure needs scores coupling or inference materialization."""
    if query_ctx is None:
        return False
    if inference_materialization is not None:
        return True
    return "scores" in query_ctx.export_services


def _resolve_query_context(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
    turn: TurnInfo,
    *,
    load_turn: Callable[[int], TurnInfo | None],
    inference_materialization: FleetInferenceMaterialization | None,
    query_context: AnalyticQueryContext | None,
) -> AnalyticQueryContext | None:
    if query_context is not None:
        return query_context
    if inference_materialization is None:
        return None

    fleet_services = FleetComputeServices(
        persistence=persistence,
        game_id=game_id,
        perspective=perspective,
        load_turn=load_turn,
        inference_materialization=inference_materialization,
    )
    return make_analytic_query_context(
        turn,
        TurnAnalyticsOptions(),
        load_turn=load_turn,
        export_services={
            "scores": inference_materialization.inference.scores_services,
            ANALYTIC_ID: fleet_services,
        },
    )

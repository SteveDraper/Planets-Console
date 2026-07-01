"""Singleflight coordinator for fleet gap-fill and forward scores/fleet unwind."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext, make_analytic_query_context
from api.analytics.export_types import ExportScope
from api.analytics.fleet.chain import (
    _complete_snapshot_turn_numbers,
    _emit_deferred_fleet_snapshot_notifications,
    _find_gap_start_turn,
    _FleetSnapshotInvalidated,
    _GapFillCoherence,
    _is_fleet_ledger_cache_hit,
    _is_fleet_snapshot_cache_hit,
    _materialize_fleet_snapshot_chain,
    _run_materialize_on_active_coherence,
    active_gap_fill_coherence,
    gap_fill_coherence_scope,
)
from api.analytics.fleet.compute_services import FleetComputeServices
from api.analytics.fleet.constants import (
    ANALYTIC_ID,
    GAP_FILL_MATERIALIZE_WAIT_TIMEOUT_SEC,
    GAP_FILL_MAX_RETRIES,
)
from api.analytics.fleet.exports import ensure_fleet_export
from api.analytics.fleet.held_solutions import FleetInferenceMaterialization
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.types import FleetTurnSnapshot, PersistedFleetLedger
from api.analytics.options import TurnAnalyticsOptions
from api.analytics.turn_roster import iter_turn_players
from api.errors import ConflictError, FleetMaterializationTimeoutError, NotFoundError
from api.models.game import TurnInfo

if TYPE_CHECKING:
    pass

_CoordinatorKey = tuple[int, int, int]


@dataclass
class _InflightMaterialization:
    target_turn: int
    generation: int
    load_turn: Callable[[int], TurnInfo | None]
    inference_materialization: FleetInferenceMaterialization | None
    query_context: AnalyticQueryContext | None
    event: threading.Event = field(default_factory=threading.Event)
    result_snapshot: FleetTurnSnapshot | None = None
    result_ledger: PersistedFleetLedger | None = None
    result_player_id: int | None = None
    error: BaseException | None = None
    leader_thread: threading.Thread | None = None


class FleetGapFillCoordinator:
    """At most one active gap-fill unwind per ``(persistence, game_id, perspective)``."""

    def __init__(
        self,
        persistence: FleetSnapshotPersistenceService,
        game_id: int,
        perspective: int,
    ) -> None:
        self._persistence = persistence
        self._game_id = game_id
        self._perspective = perspective
        self._lock = threading.Lock()
        self._inflight: _InflightMaterialization | None = None

    @property
    def epoch(self) -> int:
        """Current invalidation generation for this perspective scope."""
        return self._persistence.invalidation_generation(self._game_id, self._perspective)

    def materialize_snapshot(
        self,
        turn: TurnInfo,
        *,
        load_turn: Callable[[int], TurnInfo | None],
        inference_materialization: FleetInferenceMaterialization | None = None,
        query_context: AnalyticQueryContext | None = None,
    ) -> FleetTurnSnapshot:
        turn_number = turn.settings.turn
        cached = self._persistence.get_snapshot(self._game_id, self._perspective, turn_number)
        if _is_fleet_snapshot_cache_hit(
            self._persistence,
            self._game_id,
            self._perspective,
            turn_number,
            turn,
            cached,
        ):
            return cached

        if active_gap_fill_coherence() is not None:
            return _run_materialize_on_active_coherence(
                self._persistence,
                self._game_id,
                self._perspective,
                turn,
                load_turn=load_turn,
                inference_materialization=inference_materialization,
                materialize_player_id=None,
            )

        return self._coordinate(
            turn,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
            query_context=query_context,
            materialize_player_id=None,
        )

    def materialize_ledger_for_player(
        self,
        player_id: int,
        turn: TurnInfo,
        *,
        load_turn: Callable[[int], TurnInfo | None],
        inference_materialization: FleetInferenceMaterialization | None = None,
        query_context: AnalyticQueryContext | None = None,
    ) -> PersistedFleetLedger:
        turn_number = turn.settings.turn
        cached = self._persistence.get_ledger(
            self._game_id,
            self._perspective,
            turn_number,
            player_id,
        )
        if cached is not None and _is_fleet_ledger_cache_hit(cached):
            return cached

        if active_gap_fill_coherence() is not None:
            return _run_materialize_on_active_coherence(
                self._persistence,
                self._game_id,
                self._perspective,
                turn,
                load_turn=load_turn,
                inference_materialization=inference_materialization,
                materialize_player_id=player_id,
            )

        return self._coordinate(
            turn,
            load_turn=load_turn,
            inference_materialization=inference_materialization,
            query_context=query_context,
            materialize_player_id=player_id,
        )

    def _coordinate(
        self,
        turn: TurnInfo,
        *,
        load_turn: Callable[[int], TurnInfo | None],
        inference_materialization: FleetInferenceMaterialization | None,
        query_context: AnalyticQueryContext | None,
        materialize_player_id: int | None,
    ) -> FleetTurnSnapshot | PersistedFleetLedger:
        turn_number = turn.settings.turn
        generation = self.epoch
        inflight: _InflightMaterialization | None
        is_leader = False

        with self._lock:
            self._reap_abandoned_inflight_locked()
            if self._inflight is not None and self._inflight.event.is_set():
                self._inflight = None
            if self._inflight is not None and self._inflight.generation == generation:
                self._inflight.target_turn = max(self._inflight.target_turn, turn_number)
                inflight = self._inflight
            else:
                inflight = _InflightMaterialization(
                    target_turn=turn_number,
                    generation=generation,
                    load_turn=load_turn,
                    inference_materialization=inference_materialization,
                    query_context=query_context,
                    leader_thread=threading.current_thread(),
                )
                self._inflight = inflight
                is_leader = True

        if not is_leader:
            assert inflight is not None
            self._wait_for_inflight(inflight, turn_number, turn, load_turn, materialize_player_id)
            return self._result_for_request(
                inflight,
                turn_number,
                turn,
                load_turn,
                materialize_player_id,
            )

        assert inflight is not None
        try:
            self._run_leader_unwind(
                inflight,
                turn,
                load_turn=load_turn,
                inference_materialization=inference_materialization,
                query_context=query_context,
                materialize_player_id=materialize_player_id,
            )
        except BaseException as exc:
            inflight.error = exc
            raise
        finally:
            inflight.event.set()
            with self._lock:
                if self._inflight is inflight:
                    self._inflight = None

        if inflight.error is not None:
            raise inflight.error
        return self._result_for_request(
            inflight,
            turn_number,
            turn,
            load_turn,
            materialize_player_id,
        )

    def _reap_abandoned_inflight_locked(self) -> None:
        inflight = self._inflight
        if inflight is None or inflight.event.is_set():
            return
        leader_thread = inflight.leader_thread
        if leader_thread is not None and leader_thread.is_alive():
            return
        self._inflight = None
        inflight.event.set()

    def _wait_for_inflight(
        self,
        inflight: _InflightMaterialization,
        turn_number: int,
        turn: TurnInfo,
        load_turn: Callable[[int], TurnInfo | None],
        materialize_player_id: int | None,
    ) -> None:
        if not inflight.event.wait(timeout=GAP_FILL_MATERIALIZE_WAIT_TIMEOUT_SEC):
            raise FleetMaterializationTimeoutError(
                "fleet gap-fill for game "
                f"{self._game_id} perspective {self._perspective} turn {turn_number} "
                f"did not complete within {GAP_FILL_MATERIALIZE_WAIT_TIMEOUT_SEC}s"
            )
        if inflight.error is not None:
            return
        if materialize_player_id is None:
            cached = self._persistence.get_snapshot(self._game_id, self._perspective, turn_number)
            if cached is not None:
                return
        else:
            cached = self._persistence.get_ledger(
                self._game_id,
                self._perspective,
                turn_number,
                materialize_player_id,
            )
            if cached is not None:
                return
        if inflight.generation != self.epoch:
            return
        raise FleetMaterializationTimeoutError(
            "fleet gap-fill waiter for game "
            f"{self._game_id} perspective {self._perspective} turn {turn_number} "
            "completed without satisfying the requested snapshot"
        )

    def _result_for_request(
        self,
        inflight: _InflightMaterialization,
        turn_number: int,
        turn: TurnInfo,
        load_turn: Callable[[int], TurnInfo | None],
        materialize_player_id: int | None,
    ) -> FleetTurnSnapshot | PersistedFleetLedger:
        if inflight.error is not None:
            raise inflight.error
        if materialize_player_id is None:
            if inflight.result_snapshot is not None:
                return inflight.result_snapshot
            cached = self._persistence.get_snapshot(self._game_id, self._perspective, turn_number)
            if _is_fleet_snapshot_cache_hit(
                self._persistence,
                self._game_id,
                self._perspective,
                turn_number,
                turn,
                cached,
            ):
                assert cached is not None
                return cached
        else:
            if (
                inflight.result_ledger is not None
                and inflight.result_player_id == materialize_player_id
            ):
                return inflight.result_ledger
            cached = self._persistence.get_ledger(
                self._game_id,
                self._perspective,
                turn_number,
                materialize_player_id,
            )
            if cached is not None and _is_fleet_ledger_cache_hit(cached):
                return cached

        if inflight.generation != self.epoch:
            return self._retry_after_epoch_bump(inflight, turn, materialize_player_id)

        raise ConflictError(
            f"fleet gap-fill for game {self._game_id} perspective {self._perspective} "
            f"turn {turn_number} completed without a cache hit"
        )

    def _retry_after_epoch_bump(
        self,
        inflight: _InflightMaterialization,
        turn: TurnInfo,
        materialize_player_id: int | None,
    ) -> FleetTurnSnapshot | PersistedFleetLedger:
        if materialize_player_id is None:
            return self.materialize_snapshot(
                turn,
                load_turn=inflight.load_turn,
                inference_materialization=inflight.inference_materialization,
                query_context=inflight.query_context,
            )
        return self.materialize_ledger_for_player(
            materialize_player_id,
            turn,
            load_turn=inflight.load_turn,
            inference_materialization=inflight.inference_materialization,
            query_context=inflight.query_context,
        )

    def _run_leader_unwind(
        self,
        inflight: _InflightMaterialization,
        turn: TurnInfo,
        *,
        load_turn: Callable[[int], TurnInfo | None],
        inference_materialization: FleetInferenceMaterialization | None,
        query_context: AnalyticQueryContext | None,
        materialize_player_id: int | None,
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
            target_turn = inflight.target_turn
            if complete_before is None:
                complete_before = _complete_snapshot_turn_numbers(
                    self._persistence,
                    self._game_id,
                    self._perspective,
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
                    generation,
                )
                try:
                    with gap_fill_coherence_scope(coherence):
                        gap_start = _find_gap_start_turn(
                            self._persistence,
                            self._game_id,
                            self._perspective,
                            current_target,
                            load_turn,
                        )
                        if gap_start <= current_target:
                            if inference_materialization is not None:
                                if query_ctx is None:
                                    raise ConflictError(
                                        "fleet gap-fill requires query context when "
                                        "inference materialization is configured for "
                                        f"game {self._game_id} perspective "
                                        f"{self._perspective}"
                                    )
                                self._forward_unwind_via_export_ensure(
                                    query_ctx,
                                    gap_start,
                                    current_target,
                                    load_turn,
                                )
                            elif query_ctx is not None:
                                self._forward_unwind_via_export_ensure(
                                    query_ctx,
                                    gap_start,
                                    current_target,
                                    load_turn,
                                )
                            else:
                                target_turn_info = load_turn(current_target)
                                if target_turn_info is None:
                                    if current_target == turn.settings.turn:
                                        target_turn_info = turn
                                    else:
                                        raise NotFoundError(
                                            f"fleet gap-fill requires stored turn "
                                            f"{current_target} for game {self._game_id} "
                                            f"perspective {self._perspective}"
                                        )
                                _materialize_fleet_snapshot_chain(
                                    self._persistence,
                                    self._game_id,
                                    self._perspective,
                                    target_turn_info,
                                    load_turn=load_turn,
                                    inference_materialization=None,
                                    coherence=coherence,
                                )
                    materialized_target = current_target
                    break
                except _FleetSnapshotInvalidated:
                    if materialize_player_id is None:
                        cached = self._persistence.get_snapshot(
                            self._game_id,
                            self._perspective,
                            current_target,
                        )
                        target_turn_info = load_turn(current_target) or turn
                        if _is_fleet_snapshot_cache_hit(
                            self._persistence,
                            self._game_id,
                            self._perspective,
                            current_target,
                            target_turn_info,
                            cached,
                        ):
                            assert cached is not None
                            inflight.result_snapshot = cached
                            return
                    else:
                        cached = self._persistence.get_ledger(
                            self._game_id,
                            self._perspective,
                            current_target,
                            materialize_player_id,
                        )
                        if cached is not None and _is_fleet_ledger_cache_hit(cached):
                            inflight.result_ledger = cached
                            inflight.result_player_id = materialize_player_id
                            return
                    if attempt + 1 >= GAP_FILL_MAX_RETRIES:
                        raise ConflictError(
                            f"fleet gap-fill for game {self._game_id} "
                            f"perspective {self._perspective} turn {inflight.target_turn} "
                            f"exceeded {GAP_FILL_MAX_RETRIES} invalidation retries"
                        ) from None
                    continue
            if materialized_target is None:
                raise ConflictError(
                    f"fleet gap-fill for game {self._game_id} perspective {self._perspective} "
                    f"turn {inflight.target_turn} exceeded {GAP_FILL_MAX_RETRIES} "
                    "invalidation retries"
                )

            if inflight.target_turn > materialized_target:
                continue

            assert complete_before is not None
            _emit_deferred_fleet_snapshot_notifications(
                self._persistence,
                self._game_id,
                self._perspective,
                complete_before=complete_before,
                through_turn=materialized_target,
                load_turn=load_turn,
            )

            final_target = materialized_target
            if materialize_player_id is None:
                target_turn_info = load_turn(final_target)
                if target_turn_info is None:
                    if final_target == turn.settings.turn:
                        target_turn_info = turn
                    else:
                        raise NotFoundError(
                            f"fleet gap-fill requires stored turn {final_target} "
                            f"for game {self._game_id} perspective {self._perspective}"
                        )
                snapshot = self._persistence.get_snapshot(
                    self._game_id,
                    self._perspective,
                    final_target,
                )
                if snapshot is None:
                    raise ConflictError(
                        f"fleet snapshot gap-fill produced no document "
                        f"for game {self._game_id} perspective {self._perspective} "
                        f"turn {final_target}"
                    )
                inflight.result_snapshot = snapshot
            else:
                target_turn_info = load_turn(final_target)
                if target_turn_info is None:
                    if final_target == turn.settings.turn:
                        target_turn_info = turn
                    else:
                        raise NotFoundError(
                            f"fleet gap-fill requires stored turn {final_target} "
                            f"for game {self._game_id} perspective {self._perspective}"
                        )
                persisted = self._persistence.get_ledger(
                    self._game_id,
                    self._perspective,
                    final_target,
                    materialize_player_id,
                )
                if persisted is None:
                    raise ConflictError(
                        f"fleet ledger gap-fill produced no ledger "
                        f"for game {self._game_id} perspective {self._perspective} "
                        f"player {materialize_player_id} turn {final_target}"
                    )
                inflight.result_ledger = persisted
                inflight.result_player_id = materialize_player_id
            return

    def _forward_unwind_via_export_ensure(
        self,
        query_ctx: AnalyticQueryContext,
        gap_start: int,
        target_turn: int,
        load_turn: Callable[[int], TurnInfo | None],
    ) -> None:
        for materialize_turn in range(gap_start, target_turn + 1):
            turn_info = load_turn(materialize_turn)
            if turn_info is None:
                raise NotFoundError(
                    f"fleet forward unwind requires stored turn {materialize_turn} "
                    f"for game {self._game_id} perspective {self._perspective}"
                )
            for player in iter_turn_players(turn_info):
                scope = ExportScope(
                    game_id=self._game_id,
                    perspective=self._perspective,
                    turn=materialize_turn,
                    player_id=player.id,
                )
                ensure_fleet_export(query_ctx, scope)


_registry_lock = threading.Lock()
_coordinators: dict[_CoordinatorKey, FleetGapFillCoordinator] = {}


def coordinator_for(
    persistence: FleetSnapshotPersistenceService,
    game_id: int,
    perspective: int,
) -> FleetGapFillCoordinator:
    key = (id(persistence), game_id, perspective)
    with _registry_lock:
        coordinator = _coordinators.get(key)
        if coordinator is None:
            coordinator = FleetGapFillCoordinator(persistence, game_id, perspective)
            _coordinators[key] = coordinator
        return coordinator


def reset_coordinators() -> None:
    """Clear the process-wide coordinator registry (tests only)."""
    with _registry_lock:
        _coordinators.clear()


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

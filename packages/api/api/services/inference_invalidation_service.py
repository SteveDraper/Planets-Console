"""Coordinate scores inference persistence invalidation and in-place stream reschedule."""

from __future__ import annotations

from api.analytics.military_score_inference.inference_scheduler import (
    InferenceRowScheduler,
    get_inference_row_scheduler,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.services.inference_row_persistence_service import InferenceRowPersistenceService


class InferenceInvalidationService:
    def __init__(
        self,
        persistence: InferenceRowPersistenceService,
        scheduler: InferenceRowScheduler | None = None,
    ) -> None:
        self._persistence = persistence
        self._scheduler = scheduler

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
        scheduler = self._scheduler_instance()
        for host_turn in cleared_host_turns:
            scheduler.reschedule_all_rows(self._scope(game_id, perspective, host_turn))

    def on_hull_mask_changed(
        self,
        game_id: int,
        perspective: int,
        host_turn: int,
        player_id: int,
    ) -> None:
        self._persistence.delete_row(game_id, perspective, host_turn, player_id)
        self._scheduler_instance().reschedule_row(
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
        scope = self._scope(game_id, perspective, host_turn)
        scheduler = self._scheduler_instance()
        scheduler.clear_global_pause_for_scope(scope)
        scheduler.reschedule_all_rows(scope, force_schedule=True)

"""Lifecycle controller for one scores-table inference NDJSON stream."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from api.analytics.military_score_inference.hull_catalog_mask import ResolvedHullCatalogMask
from api.analytics.military_score_inference.inference_scheduler import InferenceRowScheduler
from api.analytics.military_score_inference.inference_stream_rows import (
    ScheduledInferenceRow,
    schedule_inference_row,
)
from api.analytics.military_score_inference.inference_stream_scope import InferenceStreamScope
from api.analytics.military_score_inference.inference_table_stream_registry import (
    attach_inference_table_stream,
    detach_inference_table_stream,
)
from api.models.game import TurnInfo


@dataclass
class InferenceTableStreamController:
    scope: InferenceStreamScope
    stream_token: str
    turn: TurnInfo
    player_ids: tuple[int, ...]
    scheduler: InferenceRowScheduler
    game_id: int
    perspective: int
    load_scoreboard_turn: Callable[[int], TurnInfo | None] | None = None
    resolve_mask_for_player: Callable[[int], ResolvedHullCatalogMask | None] | None = None
    scheduled_rows: dict[int, ScheduledInferenceRow] = field(default_factory=dict)
    finished_run_ids: set[str] = field(default_factory=set)
    stream_lock: threading.Lock = field(default_factory=threading.Lock)
    wake_multiplex: threading.Event = field(default_factory=threading.Event)

    def schedule_player_row(self, player_id: int) -> ScheduledInferenceRow | None:
        score = next((row for row in self.turn.scores if row.ownerid == player_id), None)
        if score is None:
            return None
        resolved_mask = (
            self.resolve_mask_for_player(player_id)
            if self.resolve_mask_for_player is not None
            else None
        )
        return schedule_inference_row(
            self.scheduler,
            score=score,
            turn=self.turn,
            player_id=player_id,
            game_id=self.game_id,
            perspective=self.perspective,
            load_scoreboard_turn=self.load_scoreboard_turn,
            resolved_mask=resolved_mask,
            stream_token=self.stream_token,
        )

    def cancel_player_row(self, player_id: int) -> None:
        row = self.scheduled_rows.get(player_id)
        if row is not None:
            self.scheduler.cancel_row_run(row.session.run_id)

    def current_scheduled_rows(self) -> tuple[ScheduledInferenceRow, ...]:
        with self.stream_lock:
            return tuple(self.scheduled_rows.values())

    def register_scheduled_row(self, player_id: int, row: ScheduledInferenceRow) -> None:
        with self.stream_lock:
            self.scheduled_rows[player_id] = row

    def reschedule_row(self, player_id: int) -> bool:
        with self.stream_lock:
            old_row = self.scheduled_rows.get(player_id)
            if old_row is not None:
                self.cancel_player_row(player_id)
                self.finished_run_ids.discard(old_row.session.run_id)
            self.scheduled_rows.pop(player_id, None)
            scheduled = self.schedule_player_row(player_id)
            if scheduled is None:
                return False
            self.scheduled_rows[player_id] = scheduled
            self.finished_run_ids.discard(scheduled.session.run_id)
        self.wake_multiplex.set()
        return True

    def reschedule_all_rows(self) -> bool:
        with self.stream_lock:
            for player_id in self.player_ids:
                self.cancel_player_row(player_id)
            self.finished_run_ids.clear()
            self.scheduled_rows.clear()
            for player_id in self.player_ids:
                scheduled = self.schedule_player_row(player_id)
                if scheduled is not None:
                    self.scheduled_rows[player_id] = scheduled
        self.wake_multiplex.set()
        return True

    def attach(self) -> None:
        attach_inference_table_stream(self)

    def detach(self) -> None:
        detach_inference_table_stream(self.stream_token)

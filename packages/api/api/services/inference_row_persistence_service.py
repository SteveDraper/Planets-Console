"""Persist and invalidate terminal military score build inference rows."""

from __future__ import annotations

from collections.abc import Callable

from api.analytics.military_score_inference.inference_stream_domain_events import RowComplete
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_NO_EXACT_SOLUTION,
)
from api.analytics.scores_assets import ANALYTIC_ID as SCORES_ANALYTIC_ID
from api.errors import NotFoundError, ValidationError
from api.serialization.inference_row_persistence import (
    PersistedInferenceRow,
    persisted_inference_row_from_json,
    persisted_inference_row_from_wire_complete,
    persisted_inference_row_to_json,
    upgrade_persisted_inference_row,
    wire_complete_from_persisted_row,
)
from api.storage.base import StorageBackend
from api.transport.inference_stream_wire import row_complete_to_complete_wire_event

_INFERENCE_ROWS_KEY = "inference_rows"
_PERSISTABLE_STATUSES = frozenset({STATUS_EXACT, STATUS_NO_EXACT_SOLUTION})

OnRowPersistedCallback = Callable[[int, int, int, int], None]


class InferenceRowPersistenceService:
    def __init__(
        self,
        storage: StorageBackend,
        *,
        on_row_persisted: OnRowPersistedCallback | None = None,
    ) -> None:
        self._storage = storage
        self._on_row_persisted = on_row_persisted

    @staticmethod
    def host_turn_document_key(game_id: int, perspective: int, host_turn: int) -> str:
        return f"games/{game_id}/{perspective}/turns/{host_turn}/analytics/{SCORES_ANALYTIC_ID}"

    @staticmethod
    def row_store_key(game_id: int, perspective: int, host_turn: int, player_id: int) -> str:
        document = InferenceRowPersistenceService.host_turn_document_key(
            game_id,
            perspective,
            host_turn,
        )
        return f"{document}/{_INFERENCE_ROWS_KEY}/{player_id}"

    def get_row(
        self,
        game_id: int,
        perspective: int,
        host_turn: int,
        player_id: int,
    ) -> PersistedInferenceRow | None:
        try:
            data = self._storage.get(self.row_store_key(game_id, perspective, host_turn, player_id))
        except NotFoundError:
            return None
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValidationError("stored inference row must be a JSON object")
        row = persisted_inference_row_from_json(data)
        upgraded, changed = upgrade_persisted_inference_row(row)
        if changed:
            self.put_row(game_id, perspective, host_turn, player_id, upgraded)
        return upgraded

    def wire_complete_for_row(
        self,
        game_id: int,
        perspective: int,
        host_turn: int,
        player_id: int,
    ) -> dict[str, object] | None:
        row = self.get_row(game_id, perspective, host_turn, player_id)
        if row is None:
            return None
        return wire_complete_from_persisted_row(row)

    def put_row(
        self,
        game_id: int,
        perspective: int,
        host_turn: int,
        player_id: int,
        row: PersistedInferenceRow,
        *,
        notify: bool = True,
    ) -> None:
        """Store one inference row.

        When ``notify`` is true (default), invoke ``on_row_persisted`` so fleet
        invalidation can clear ledgers from this host turn. Pass ``notify=False``
        for first-write cheap terminals (``no_prior_turn`` / ``player_not_found``)
        established during ensure: those close materialization evidence without
        being a scores refine that should abort an in-flight fleet gap-fill.
        """
        prepared, _ = upgrade_persisted_inference_row(row)
        self._storage.put(
            self.row_store_key(game_id, perspective, host_turn, player_id),
            persisted_inference_row_to_json(prepared),
        )
        if notify and self._on_row_persisted is not None:
            self._on_row_persisted(game_id, perspective, host_turn, player_id)

    @property
    def on_row_persisted(self) -> OnRowPersistedCallback | None:
        return self._on_row_persisted

    @on_row_persisted.setter
    def on_row_persisted(self, callback: OnRowPersistedCallback | None) -> None:
        self._on_row_persisted = callback

    def delete_row(
        self,
        game_id: int,
        perspective: int,
        host_turn: int,
        player_id: int,
    ) -> None:
        try:
            self._storage.delete(self.row_store_key(game_id, perspective, host_turn, player_id))
        except NotFoundError:
            pass

    def delete_host_turn_document(
        self,
        game_id: int,
        perspective: int,
        host_turn: int,
    ) -> None:
        try:
            self._storage.delete(self.host_turn_document_key(game_id, perspective, host_turn))
        except NotFoundError:
            pass

    def invalidate_for_turn_write(
        self,
        game_id: int,
        perspective: int,
        turn_number: int,
    ) -> set[int]:
        """Delete inference persistence for turn T and T-1; return cleared host turns."""
        cleared: set[int] = set()
        for host_turn in (turn_number, turn_number - 1):
            if host_turn < 1:
                continue
            self.delete_host_turn_document(game_id, perspective, host_turn)
            cleared.add(host_turn)
        return cleared

    def persist_row_complete(
        self,
        session: InferenceRowStreamSession,
        event: RowComplete,
    ) -> None:
        status = event.wire_payload.status
        if status not in _PERSISTABLE_STATUSES:
            return
        wire_event = row_complete_to_complete_wire_event(
            event,
            observation=session.observation,
            turn=session.turn,
        )
        row = persisted_inference_row_from_wire_complete(wire_event)
        self.put_row(
            session.game_id,
            session.perspective,
            session.turn_number,
            session.player_id,
            row,
        )

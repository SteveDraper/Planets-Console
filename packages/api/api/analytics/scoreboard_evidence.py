"""Scoreboard evidence generation compared with the fleet evidence mark.

Write stamps and paint annotation both live here. The integer comes from
fleet persistence ``evidence_mark``. None means fleet is not on the context:
a row being written is left unchanged, and a paint omits ``evidenceMark``.
Zero is a real mark. A stored row whose generation field is missing compares
as 0. No stored row stays unmarked.

Live durable completes are painted after persist has written the row. The
generation on that paint is the integer that write stored, read back by
``annotate_scoreboard_paint``. Replay and admission call the same function
for a row that is already stored.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.injected_services import lookup_fleet_compute_services
from api.serialization.inference_row_persistence import wire_complete_from_persisted_row
from api.transport.inference_stream import inference_stored_row_event

if TYPE_CHECKING:
    from api.serialization.inference_row_persistence import PersistedInferenceRow


class ScoreboardRowStore(Protocol):
    """Persistence surface this module reads: one stored scoreboard row."""

    def get_row(
        self,
        game_id: int,
        perspective: int,
        host_turn: int,
        player_id: int,
    ) -> PersistedInferenceRow | None: ...


# ``stored_row`` is not a multiplex terminal; ``complete`` is.
_EVIDENCE_EVENT_TYPES = frozenset({"complete", "stored_row"})


def stamp_scoreboard_row_for_context(
    row: PersistedInferenceRow,
    query_context: AnalyticQueryContext | None,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
) -> PersistedInferenceRow:
    """Stamp the current fleet mark onto a scoreboard row being written.

    ``None`` leaves the row unchanged. Zero is stored as generation 0.
    """
    evidence_mark = _evidence_mark_for_player(
        query_context,
        game_id=game_id,
        perspective=perspective,
        player_id=player_id,
    )
    if evidence_mark is None:
        return row
    return replace(row, evidence_generation=evidence_mark)


def annotate_scoreboard_paint(
    event: dict[str, object],
    *,
    persistence: ScoreboardRowStore | None,
    query_context: AnalyticQueryContext | None,
    game_id: int,
    perspective: int,
    turn: int,
    player_id: int,
) -> dict[str, object]:
    """Put the stored generation and the current mark on one scoreboard paint.

    ``complete`` and ``stored_row`` carry the pair. Other event types are
    unchanged. A missing or non-int generation on a row that exists is 0.
    No stored row leaves the event unmarked, so a skip with no scoreboard
    file stays the dash alone. A None mark omits ``evidenceMark``.

    Live durable completes call this after persist has written the row. The
    generation on the paint is that stored integer. It is not a second copy
    of the mark read here; the mark can move between the write and this read.
    """
    if event.get("type") not in _EVIDENCE_EVENT_TYPES:
        return event
    stored = _stored_row(persistence, game_id, perspective, turn, player_id)
    if stored is None:
        return event
    painted = dict(event)
    # JSON true is a bool, and bool is an int. That is not a generation.
    generation = stored.evidence_generation
    if isinstance(generation, bool) or not isinstance(generation, int):
        generation = 0
    painted["evidenceGeneration"] = generation
    evidence_mark = _evidence_mark_for_player(
        query_context,
        game_id=game_id,
        perspective=perspective,
        player_id=player_id,
    )
    if evidence_mark is not None:
        painted["evidenceMark"] = evidence_mark
    return painted


def stored_scoreboard_prelude_event(
    *,
    persistence: ScoreboardRowStore | None,
    query_context: AnalyticQueryContext | None,
    game_id: int,
    perspective: int,
    turn: int,
    player_id: int,
) -> dict[str, object] | None:
    """Non-terminal paint of a stored row, or None when nothing is stored.

    Missing generation is 0. The scheduled run stays open; accept follows.
    """
    stored = _stored_row(persistence, game_id, perspective, turn, player_id)
    if stored is None:
        return None
    return annotate_scoreboard_paint(
        inference_stored_row_event(wire_complete_from_persisted_row(stored)),
        persistence=persistence,
        query_context=query_context,
        game_id=game_id,
        perspective=perspective,
        turn=turn,
        player_id=player_id,
    )


def _evidence_mark_for_player(
    ctx: AnalyticQueryContext | None,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
) -> int | None:
    """Current fleet evidence mark, or None when fleet is not on this context."""
    if ctx is None:
        return None
    services = lookup_fleet_compute_services(ctx)
    if services is None:
        return None
    return services.persistence.evidence_mark(game_id, perspective, player_id).evidence_generation


def _stored_row(
    persistence: ScoreboardRowStore | None,
    game_id: int,
    perspective: int,
    turn: int,
    player_id: int,
) -> PersistedInferenceRow | None:
    if persistence is None:
        return None
    return persistence.get_row(game_id, perspective, turn, player_id)

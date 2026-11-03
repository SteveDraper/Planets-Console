"""Scoreboard evidence generation compared with the fleet evidence mark.

Write stamps and replay annotation both live here. The integer comes from
fleet persistence ``evidence_mark``. Callers pass a query context into the
mark read, or an already-resolved mark into the stamp and the annotation.
None means fleet is not on the context and freshness fields stay omitted.
Zero is a real mark. A stored row whose generation field is missing compares
as 0. No stored row stays unmarked.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.injected_services import lookup_fleet_compute_services
from api.serialization.inference_row_persistence import wire_complete_from_persisted_row
from api.transport.inference_stream import (
    inference_stored_row_event,
    stamp_inference_evidence_fields,
)

if TYPE_CHECKING:
    from api.serialization.inference_row_persistence import PersistedInferenceRow


def evidence_mark_for_player(
    ctx: AnalyticQueryContext | None,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
) -> int | None:
    """Current fleet evidence mark, or None when fleet is not on this context.

    None means the caller should omit freshness fields. Zero is a real mark.
    """
    if ctx is None:
        return None
    services = lookup_fleet_compute_services(ctx)
    if services is None:
        return None
    return services.persistence.evidence_mark(game_id, perspective, player_id).evidence_generation


def stamp_scoreboard_evidence_generation(
    row: PersistedInferenceRow,
    evidence_mark: int | None,
) -> PersistedInferenceRow:
    """Stamp an already-resolved generation onto a row being written.

    ``None`` leaves the row unchanged. Zero is stored as generation 0.
    """
    if evidence_mark is None:
        return row
    return replace(row, evidence_generation=evidence_mark)


def stamp_scoreboard_row_for_context(
    row: PersistedInferenceRow,
    query_context: AnalyticQueryContext | None,
    *,
    game_id: int,
    perspective: int,
    player_id: int,
) -> PersistedInferenceRow:
    """Stamp the current fleet mark onto a scoreboard row being written."""
    return stamp_scoreboard_evidence_generation(
        row,
        evidence_mark_for_player(
            query_context,
            game_id=game_id,
            perspective=perspective,
            player_id=player_id,
        ),
    )


def annotate_stored_scoreboard_complete(
    event: dict[str, object],
    *,
    stored: PersistedInferenceRow | None,
    evidence_mark: int | None,
) -> dict[str, object]:
    """Put the stored generation and the current mark on a scoreboard paint.

    ``complete`` and ``stored_row`` both carry the pair. A missing generation
    on a row that exists is 0. No stored row omits both fields, so a skip with
    no scoreboard file stays the dash alone.
    """
    if stored is None:
        return event
    return stamp_inference_evidence_fields(
        event,
        evidence_generation=_stored_evidence_generation(stored),
        evidence_mark=evidence_mark,
    )


def stored_scoreboard_prelude_event(
    stored: PersistedInferenceRow,
    *,
    evidence_mark: int | None,
) -> dict[str, object]:
    """Non-terminal paint of a stored row: its status, generation, and mark.

    Missing generation is 0. The scheduled run stays open; accept follows.
    """
    return annotate_stored_scoreboard_complete(
        inference_stored_row_event(wire_complete_from_persisted_row(stored)),
        stored=stored,
        evidence_mark=evidence_mark,
    )


def _stored_evidence_generation(row: PersistedInferenceRow) -> int:
    """Generation on a row that exists. A missing or non-int field is 0."""
    generation = row.evidence_generation
    if isinstance(generation, bool) or not isinstance(generation, int):
        return 0
    return generation

"""Fleet job-wire fields for the submission open.

The shared open-turn and catch-up rules live in ``api.analytics.off_mode``.
This module writes those fields onto a fleet job wire and reads the stored
backfill choice only when the wire does not already carry one.
"""

from __future__ import annotations

from typing import Any

from api.analytics.export_context import AnalyticQueryContext
from api.analytics.fleet.injected_services import resolve_fleet_services
from api.analytics.off_mode import (
    BACKFILL_EARLIER_TURNS_WIRE_FIELD,
    apply_off_mode_job_wire_fields,
    parse_off_mode_wire,
)
from api.compute.scope import ComputeScope


def _concrete_open_turn(open_turn: int | None) -> int | None:
    """Return a submission root, or None when this call has no open turn.

    A bool is not a turn. ``parse_off_mode_wire`` rejects it.
    """
    if open_turn is None:
        return None
    return parse_off_mode_wire({"openTurn": open_turn}).open_turn


def stamp_submission_open(
    wire: dict[str, Any],
    scope: ComputeScope,
    ctx: AnalyticQueryContext,
    open_turn: int | None,
    *,
    backfill_earlier_turns: bool | None,
) -> None:
    """Write the submission root and its backfill choice onto a fleet job wire.

    A carried choice is written and storage is not read. A direct builder call
    with no carried choice reads the record only when a concrete open turn is
    being stamped. No concrete open and no carried choice leaves those fields
    off the wire.
    """
    if isinstance(scope.turn, bool) or not isinstance(scope.turn, int):
        raise ValueError("fleet job wire requires concrete turn")
    concrete = _concrete_open_turn(open_turn)
    enabled = backfill_earlier_turns
    if enabled is None:
        if concrete is None:
            wire.pop("openTurn", None)
            wire.pop("catchUp", None)
            return
        services = resolve_fleet_services(ctx)
        enabled = services.persistence.backfill_earlier_turns_enabled(scope.game_id)
    if concrete is None:
        wire.pop("openTurn", None)
        wire.pop("catchUp", None)
    else:
        apply_off_mode_job_wire_fields(
            wire,
            open_turn=concrete,
            turn=scope.turn,
            backfill_enabled=enabled,
        )
    wire[BACKFILL_EARLIER_TURNS_WIRE_FIELD] = enabled

"""Off-mode fields on a job wire and a persist payload.

``stamp_submission_open`` writes ``openTurn``, ``catchUp``, and
``backfillEarlierTurns`` from a submission open the caller already resolved.
``parse_off_mode_wire`` reads those fields and ``playerInvalidationGeneration``.
``copy_submission_open_fields`` copies the parsed fields onto a persist payload.

Writing the submission-open fields needs ``SubmissionOpen`` and ``ComputeScope``.
It does not read the stored backfill record.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from api.compute.scope import ComputeScope
from api.compute.submission_open import SubmissionOpen
from api.exceptions import ValidationError

BACKFILL_EARLIER_TURNS_WIRE_FIELD = "backfillEarlierTurns"
OPEN_TURN_WIRE_FIELD = "openTurn"
CATCH_UP_WIRE_FIELD = "catchUp"
_PLAYER_INVALIDATION_GENERATION_FIELD = "playerInvalidationGeneration"


def _require_json_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} must be an integer")
    return value


def _require_json_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{field} must be a boolean")
    return value


@dataclass(frozen=True)
class OffModeWireFields:
    """Off-mode fields on a fleet job wire or persist payload.

    ``open_turn`` is None when the wire is not an off-mode open. ``catch_up``
    is true only for an earlier hop of that open. ``backfill_earlier_turns``
    is None when the wire does not carry the choice. ``player_invalidation_generation``
    is None when the wire does not carry an epoch.
    """

    open_turn: int | None
    catch_up: bool
    backfill_earlier_turns: bool | None
    player_invalidation_generation: int | None


def parse_off_mode_wire(wire: Mapping[str, object]) -> OffModeWireFields:
    """Read openTurn, catchUp, backfillEarlierTurns, and playerInvalidationGeneration.

    A missing field keeps the meaning above. A present field of the wrong JSON
    type is a ``ValidationError``. ``catchUp: true`` without ``openTurn`` is a
    ``ValidationError``. Bool is not an integer.
    """
    if OPEN_TURN_WIRE_FIELD in wire:
        open_turn = _require_json_int(wire[OPEN_TURN_WIRE_FIELD], field=OPEN_TURN_WIRE_FIELD)
    else:
        open_turn = None

    if CATCH_UP_WIRE_FIELD in wire:
        catch_up = _require_json_bool(wire[CATCH_UP_WIRE_FIELD], field=CATCH_UP_WIRE_FIELD)
    else:
        catch_up = False
    if catch_up and open_turn is None:
        raise ValidationError("catchUp requires openTurn")

    if BACKFILL_EARLIER_TURNS_WIRE_FIELD in wire:
        backfill_earlier_turns = _require_json_bool(
            wire[BACKFILL_EARLIER_TURNS_WIRE_FIELD],
            field=BACKFILL_EARLIER_TURNS_WIRE_FIELD,
        )
    else:
        backfill_earlier_turns = None

    if _PLAYER_INVALIDATION_GENERATION_FIELD in wire:
        player_invalidation_generation = _require_json_int(
            wire[_PLAYER_INVALIDATION_GENERATION_FIELD],
            field=_PLAYER_INVALIDATION_GENERATION_FIELD,
        )
    else:
        player_invalidation_generation = None

    return OffModeWireFields(
        open_turn=open_turn,
        catch_up=catch_up,
        backfill_earlier_turns=backfill_earlier_turns,
        player_invalidation_generation=player_invalidation_generation,
    )


def copy_submission_open_fields(
    job_wire: Mapping[str, Any],
    payload: MutableMapping[str, Any],
) -> None:
    """Copy submission open fields and the job epoch onto a persist payload.

    A wire without an integer open turn leaves ``openTurn`` and ``catchUp``
    unset. ``catchUp`` is copied only together with that open turn. A carried
    ``backfillEarlierTurns`` boolean is copied on its own, including when
    backfill is on and the open turn is left off the wire. A carried integer
    ``playerInvalidationGeneration`` is copied. A missing epoch stays off the
    payload so persist can reject it.
    """
    fields = parse_off_mode_wire(job_wire)
    if fields.backfill_earlier_turns is not None:
        payload[BACKFILL_EARLIER_TURNS_WIRE_FIELD] = fields.backfill_earlier_turns
    if fields.player_invalidation_generation is not None:
        payload[_PLAYER_INVALIDATION_GENERATION_FIELD] = fields.player_invalidation_generation
    if fields.open_turn is None:
        return
    payload[OPEN_TURN_WIRE_FIELD] = fields.open_turn
    if fields.catch_up:
        payload[CATCH_UP_WIRE_FIELD] = True


def stamp_submission_open(
    wire: dict[str, Any],
    scope: ComputeScope,
    submission_open: SubmissionOpen,
) -> None:
    """Write one submission open onto a fleet job wire.

    The carried open is copied as resolved. ``openTurn`` and ``catchUp`` are
    present only when backfill is off and the open turn is set. ``catchUp`` is
    true for an earlier hop of that open and false on the open turn itself.
    ``backfillEarlierTurns`` is the carried choice.
    """
    turn = scope.turn
    if isinstance(turn, bool) or not isinstance(turn, int):
        raise ValueError("fleet job wire requires concrete turn")
    wire.pop(OPEN_TURN_WIRE_FIELD, None)
    wire.pop(CATCH_UP_WIRE_FIELD, None)
    wire[BACKFILL_EARLIER_TURNS_WIRE_FIELD] = submission_open.backfill_earlier_turns
    open_turn = submission_open.open_turn
    if open_turn is None or submission_open.backfill_earlier_turns:
        return
    wire[OPEN_TURN_WIRE_FIELD] = open_turn
    wire[CATCH_UP_WIRE_FIELD] = turn < open_turn

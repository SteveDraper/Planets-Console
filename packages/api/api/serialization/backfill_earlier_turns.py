"""Codec for the per-game Backfill earlier turns record."""

from __future__ import annotations

from api.errors import ValidationError

BACKFILL_EARLIER_TURNS_FIELD = "backfillEarlierTurns"


def backfill_earlier_turns_document(enabled: bool) -> dict[str, bool]:
    """JSON document for a stored Backfill earlier turns choice."""
    return {BACKFILL_EARLIER_TURNS_FIELD: enabled}


def backfill_earlier_turns_enabled(payload: dict) -> bool:
    """Return the boolean stored in a Backfill earlier turns record."""
    if set(payload) != {BACKFILL_EARLIER_TURNS_FIELD}:
        raise ValidationError(
            "Backfill earlier turns record must contain only backfillEarlierTurns."
        )
    value = payload[BACKFILL_EARLIER_TURNS_FIELD]
    if not isinstance(value, bool):
        raise ValidationError("backfillEarlierTurns must be a boolean.")
    return value

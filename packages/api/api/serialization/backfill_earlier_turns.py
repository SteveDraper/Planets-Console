"""Codec and storage read for the per-game Backfill earlier turns record."""

from __future__ import annotations

from api.errors import NotFoundError, ValidationError
from api.storage.base import StorageBackend

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


def backfill_earlier_turns_store_key(game_id: int) -> str:
    """Storage path for the one Backfill earlier turns record of ``game_id``."""
    return f"games/{game_id}/backfill-earlier-turns"


def read_backfill_earlier_turns(storage: StorageBackend, game_id: int) -> bool:
    """Return the stored Backfill earlier turns choice.

    A missing record is off. A present record is decoded by the codec, so a
    non-object or a malformed document is rejected. This read does not check
    that the game exists and does not submit a walk.
    """
    try:
        raw = storage.get(backfill_earlier_turns_store_key(game_id))
    except NotFoundError:
        return False
    label = f"backfill earlier turns for game {game_id}"
    if not isinstance(raw, dict):
        raise ValidationError(f"Expected JSON object for {label}, got {type(raw).__name__}")
    return backfill_earlier_turns_enabled(raw)

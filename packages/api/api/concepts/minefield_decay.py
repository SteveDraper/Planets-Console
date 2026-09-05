"""Default (non-nebula) minefield decay: remaining ``round(0.95x) - 1`` per field."""

from __future__ import annotations

DEFAULT_MINEFIELD_DECAY_KEEP_FRACTION = 0.95


def remaining_units_after_default_decay(units: int) -> int:
    """Mines remaining in one field after one turn of default decay."""
    if units <= 0:
        return 0
    return max(0, round(units * DEFAULT_MINEFIELD_DECAY_KEEP_FRACTION) - 1)


def lost_units_after_default_decay(units: int) -> int:
    """Units destroyed in one field by one turn of default decay."""
    if units <= 0:
        return 0
    return units - remaining_units_after_default_decay(units)


def equal_split_field_units(total_units: int, field_count: int) -> tuple[int, ...]:
    """Split ``total_units`` across ``field_count`` fields as evenly as possible.

    Remainder units go to the first fields. Empty or non-positive field counts
    yield no fields (the blob approximation is a single implied field).
    """
    if field_count <= 0 or total_units <= 0:
        return ()
    base, remainder = divmod(total_units, field_count)
    return tuple(base + 1 if index < remainder else base for index in range(field_count))

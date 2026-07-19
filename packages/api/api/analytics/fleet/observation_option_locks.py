"""Shared observation-lock compatibility for fleet option sets.

Ingest merge and inference refine both use :func:`option_set_respecting_locks`
so hull, component ids, and positive weapon counts stay consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetFieldKnown,
    FleetShipRecord,
)


@dataclass(frozen=True, slots=True)
class ObservationComponentLocks:
    """Axes locked by a direct observation (ids and positive counts)."""

    hull_id: int | None = None
    engine_id: int | None = None
    beam_id: int | None = None
    torp_id: int | None = None
    beam_count: int | None = None
    launcher_count: int | None = None

    @property
    def has_any_lock(self) -> bool:
        return any(
            value is not None
            for value in (
                self.hull_id,
                self.engine_id,
                self.beam_id,
                self.torp_id,
                self.beam_count,
                self.launcher_count,
            )
        )


def observation_locks_from_record(record: FleetShipRecord) -> ObservationComponentLocks:
    """Derive locks from record fields plus unanimous positive counts on option sets."""
    fields = record.fields
    hull_id = (
        fields.hull.value
        if isinstance(fields.hull, FleetFieldKnown) and isinstance(fields.hull.value, int)
        else None
    )
    engine_id = _positive_known_id(fields.engine)
    beam_id = _positive_known_id(fields.beams)
    torp_id = _positive_known_id(fields.launchers)
    beam_count, launcher_count = _unanimous_positive_counts(record.build_option_sets)
    return ObservationComponentLocks(
        hull_id=hull_id,
        engine_id=engine_id,
        beam_id=beam_id,
        torp_id=torp_id,
        beam_count=beam_count,
        launcher_count=launcher_count,
    )


def observation_locks_from_option_set(observed: FleetBuildOptionSet) -> ObservationComponentLocks:
    """Locks carried on one observed option set (ingest merge source)."""
    return ObservationComponentLocks(
        hull_id=observed.hull_id,
        engine_id=observed.engine_id if observed.engine_id and observed.engine_id > 0 else None,
        beam_id=observed.beam_id if observed.beam_id and observed.beam_id > 0 else None,
        torp_id=observed.torp_id if observed.torp_id and observed.torp_id > 0 else None,
        beam_count=observed.beam_count if observed.beam_count and observed.beam_count > 0 else None,
        launcher_count=(
            observed.launcher_count
            if observed.launcher_count and observed.launcher_count > 0
            else None
        ),
    )


def option_set_compatible_with_locks(
    option_set: FleetBuildOptionSet,
    locks: ObservationComponentLocks,
) -> bool:
    """False when a set contradicts a positively locked axis."""
    if locks.hull_id is not None and option_set.hull_id != locks.hull_id:
        return False
    if locks.engine_id is not None and option_set.engine_id not in (None, locks.engine_id):
        return False
    if locks.beam_id is not None and option_set.beam_id not in (None, locks.beam_id):
        return False
    if locks.torp_id is not None and option_set.torp_id not in (None, locks.torp_id):
        return False
    if locks.beam_count is not None and option_set.beam_count not in (None, locks.beam_count):
        return False
    if locks.launcher_count is not None and option_set.launcher_count not in (
        None,
        locks.launcher_count,
    ):
        return False
    return True


def option_set_respecting_locks(
    option_set: FleetBuildOptionSet,
    locks: ObservationComponentLocks,
) -> FleetBuildOptionSet | None:
    """Return ``option_set`` with locks merged, or None when incompatible."""
    if not option_set_compatible_with_locks(option_set, locks):
        return None
    updates: dict[str, object] = {}
    if locks.hull_id is not None:
        updates["hull_id"] = locks.hull_id
    if locks.engine_id is not None:
        updates["engine_id"] = locks.engine_id
    if locks.beam_id is not None:
        updates["beam_id"] = locks.beam_id
    if locks.torp_id is not None:
        updates["torp_id"] = locks.torp_id
    if locks.beam_count is not None:
        updates["beam_count"] = locks.beam_count
    if locks.launcher_count is not None:
        updates["launcher_count"] = locks.launcher_count
    return replace(option_set, **updates) if updates else option_set


def option_sets_respecting_locks(
    option_sets: tuple[FleetBuildOptionSet, ...] | list[FleetBuildOptionSet],
    locks: ObservationComponentLocks,
) -> tuple[FleetBuildOptionSet, ...]:
    """Filter and merge a sequence of option sets against observation locks."""
    adjusted: list[FleetBuildOptionSet] = []
    for option_set in option_sets:
        merged = option_set_respecting_locks(option_set, locks)
        if merged is not None:
            adjusted.append(merged)
    return tuple(adjusted)


def _positive_known_id(constraint: object) -> int | None:
    if (
        isinstance(constraint, FleetFieldKnown)
        and isinstance(constraint.value, int)
        and constraint.value > 0
    ):
        return constraint.value
    return None


def _unanimous_positive_counts(
    option_sets: list[FleetBuildOptionSet],
) -> tuple[int | None, int | None]:
    beam_counts = {
        option_set.beam_count
        for option_set in option_sets
        if option_set.beam_count is not None and option_set.beam_count > 0
    }
    launcher_counts = {
        option_set.launcher_count
        for option_set in option_sets
        if option_set.launcher_count is not None and option_set.launcher_count > 0
    }
    beam_count = next(iter(beam_counts)) if len(beam_counts) == 1 else None
    launcher_count = next(iter(launcher_counts)) if len(launcher_counts) == 1 else None
    return beam_count, launcher_count

"""Analytic-agnostic GIL overlap admission for remapped thread-pool steps."""

from __future__ import annotations

from api.compute import backend_runtime
from api.compute.profile import GilOverlapClass


def frozen_gil_overlap_enabled() -> bool:
    """Frozen console packages hold exclusive Python off SAT in-flight workers."""
    return backend_runtime.process_is_frozen()


def exclusive_step_may_run(*, native_release_in_flight: int) -> bool:
    """Exclusive Python may run only when no native-release SAT step is executing."""
    return native_release_in_flight == 0


def native_release_step_may_run(
    *,
    exclusive_queued: bool,
    exclusive_in_flight: int,
) -> bool:
    """Native-release SAT may run only when no exclusive step is queued or executing."""
    return not exclusive_queued and exclusive_in_flight == 0


def pool_item_may_run_under_gil_overlap(
    gil_overlap: GilOverlapClass,
    *,
    enabled: bool,
    native_release_in_flight: int,
    exclusive_queued: bool,
    exclusive_in_flight: int,
) -> bool:
    """Return whether a queued item may dequeue under the frozen overlap policy."""
    if not enabled:
        return True
    if gil_overlap == "exclusive":
        return exclusive_step_may_run(native_release_in_flight=native_release_in_flight)
    if gil_overlap == "native_release":
        return native_release_step_may_run(
            exclusive_queued=exclusive_queued,
            exclusive_in_flight=exclusive_in_flight,
        )
    return True

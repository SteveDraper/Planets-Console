"""Thin derived rollup over the compute concurrency timeline (no auto-verdict)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from api.compute.diagnostics.timeline import ComputeConcurrencyEvent


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


def _player_id_from_scope_key(scope_key: str) -> int | None:
    """Best-effort player id from a formatted scope key (``...@plN`` or ``.../plN/...``)."""
    for part in scope_key.replace("/", "@").split("@"):
        if part.startswith("pl") and part[2:].isdigit():
            return int(part[2:])
    return None


@dataclass(frozen=True)
class ConcurrencyTimelineRollup:
    """Assistive aggregates for bottleneck classification (not an auto-label)."""

    event_count: int
    unique_players: tuple[int, ...]
    backend_histogram: dict[str, int]
    duration_by_backend_ms: dict[str, dict[str, float | None]]
    scoped_ready_depth: dict[str, float | None]
    scoped_in_flight: dict[str, float | None]
    global_in_flight: dict[str, float | None]
    max_scoped_ready_depth: int
    max_scoped_in_flight: int
    max_global_in_flight: int
    configured_workers: int | None


def build_concurrency_timeline_rollup(
    events: tuple[ComputeConcurrencyEvent, ...],
) -> ConcurrencyTimelineRollup:
    """Derive a thin rollup from timeline events. Does not declare a bottleneck class."""
    if not events:
        return ConcurrencyTimelineRollup(
            event_count=0,
            unique_players=(),
            backend_histogram={},
            duration_by_backend_ms={},
            scoped_ready_depth={"p50": None, "p95": None, "max": None},
            scoped_in_flight={"p50": None, "p95": None, "max": None},
            global_in_flight={"p50": None, "p95": None, "max": None},
            max_scoped_ready_depth=0,
            max_scoped_in_flight=0,
            max_global_in_flight=0,
            configured_workers=None,
        )

    players: set[int] = set()
    backend_counts: Counter[str] = Counter()
    durations_by_backend: dict[str, list[float]] = {}
    ready_depths: list[float] = []
    scoped_in_flights: list[float] = []
    global_in_flights: list[float] = []
    configured_workers: int | None = None

    for event in events:
        player_id = _player_id_from_scope_key(event.scope_key)
        if player_id is not None:
            players.add(player_id)
        if event.backend:
            backend_counts[event.backend] += 1
        if event.duration_ms is not None and event.backend:
            durations_by_backend.setdefault(event.backend, []).append(event.duration_ms)
        ready_depths.append(float(event.gauges.scoped_ready_depth))
        scoped_in_flights.append(float(event.gauges.scoped_in_flight_count))
        global_in_flights.append(float(event.gauges.global_in_flight_count))
        configured_workers = event.gauges.configured_workers

    duration_by_backend_ms: dict[str, dict[str, float | None]] = {}
    for backend, values in sorted(durations_by_backend.items()):
        ordered = sorted(values)
        duration_by_backend_ms[backend] = {
            "count": float(len(ordered)),
            "p50": _percentile(ordered, 0.50),
            "p95": _percentile(ordered, 0.95),
            "max": ordered[-1] if ordered else None,
        }

    ready_sorted = sorted(ready_depths)
    scoped_if_sorted = sorted(scoped_in_flights)
    global_if_sorted = sorted(global_in_flights)

    return ConcurrencyTimelineRollup(
        event_count=len(events),
        unique_players=tuple(sorted(players)),
        backend_histogram=dict(sorted(backend_counts.items())),
        duration_by_backend_ms=duration_by_backend_ms,
        scoped_ready_depth={
            "p50": _percentile(ready_sorted, 0.50),
            "p95": _percentile(ready_sorted, 0.95),
            "max": ready_sorted[-1] if ready_sorted else None,
        },
        scoped_in_flight={
            "p50": _percentile(scoped_if_sorted, 0.50),
            "p95": _percentile(scoped_if_sorted, 0.95),
            "max": scoped_if_sorted[-1] if scoped_if_sorted else None,
        },
        global_in_flight={
            "p50": _percentile(global_if_sorted, 0.50),
            "p95": _percentile(global_if_sorted, 0.95),
            "max": global_if_sorted[-1] if global_if_sorted else None,
        },
        max_scoped_ready_depth=int(ready_sorted[-1]) if ready_sorted else 0,
        max_scoped_in_flight=int(scoped_if_sorted[-1]) if scoped_if_sorted else 0,
        max_global_in_flight=int(global_if_sorted[-1]) if global_if_sorted else 0,
        configured_workers=configured_workers,
    )


def rollup_to_wire(rollup: ConcurrencyTimelineRollup) -> dict[str, Any]:
    """CamelCase wire shape for the concurrency timeline rollup."""
    return {
        "eventCount": rollup.event_count,
        "uniquePlayers": list(rollup.unique_players),
        "backendHistogram": rollup.backend_histogram,
        "durationByBackendMs": rollup.duration_by_backend_ms,
        "scopedReadyDepth": rollup.scoped_ready_depth,
        "scopedInFlight": rollup.scoped_in_flight,
        "globalInFlight": rollup.global_in_flight,
        "maxScopedReadyDepth": rollup.max_scoped_ready_depth,
        "maxScopedInFlight": rollup.max_scoped_in_flight,
        "maxGlobalInFlight": rollup.max_global_in_flight,
        "configuredWorkers": rollup.configured_workers,
    }

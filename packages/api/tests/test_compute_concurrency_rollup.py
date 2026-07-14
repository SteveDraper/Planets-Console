"""Unit tests for concurrency timeline rollup (no auto-verdict)."""

from __future__ import annotations

from api.compute.diagnostics.rollup import (
    build_concurrency_timeline_rollup,
    rollup_to_wire,
)
from api.compute.diagnostics.timeline import OccupancyGauges, make_concurrency_event


def _event(
    *,
    kind: str = "complete",
    scope_key: str = "g1/p1/t8/pl3/scores",
    backend: str | None = "thread",
    duration_ms: float | None = 10.0,
    ready: int = 1,
    scoped_if: int = 1,
    global_if: int = 2,
) -> object:
    return make_concurrency_event(
        kind=kind,  # type: ignore[arg-type]
        scope_key=scope_key,
        execution_key=f"{scope_key}|{kind}",
        gauges=OccupancyGauges(
            scoped_ready_depth=ready,
            scoped_in_flight_count=scoped_if,
            global_in_flight_count=global_if,
            global_queue_depth=0,
            configured_workers=4,
        ),
        step_kind="tier_solve",
        step_index=0,
        backend=backend,
        duration_ms=duration_ms,
        terminal_state="success" if kind == "complete" else None,
    )


def test_rollup_empty_events():
    rollup = build_concurrency_timeline_rollup(())
    wire = rollup_to_wire(rollup)
    assert wire["eventCount"] == 0
    assert wire["uniquePlayers"] == []
    assert wire["backendHistogram"] == {}
    assert wire["configuredWorkers"] is None
    assert "bottleneckClass" not in wire
    assert "verdict" not in wire


def test_rollup_unique_players_backend_histogram_and_depths():
    events = (
        _event(scope_key="g1/p1/t8/pl3/scores", backend="thread", ready=1, global_if=1),
        _event(scope_key="g1/p1/t8/pl7/fleet", backend="interpreter", ready=3, global_if=4),
        _event(scope_key="g1/p1/t8/pl3/scores", backend="thread", ready=2, global_if=2),
    )
    rollup = build_concurrency_timeline_rollup(events)  # type: ignore[arg-type]
    assert rollup.unique_players == (3, 7)
    assert rollup.backend_histogram == {"interpreter": 1, "thread": 2}
    assert rollup.max_scoped_ready_depth == 3
    assert rollup.max_global_in_flight == 4
    assert rollup.configured_workers == 4
    assert rollup.scoped_ready_depth["max"] == 3.0
    wire = rollup_to_wire(rollup)
    assert wire["uniquePlayers"] == [3, 7]
    assert "bottleneckClass" not in wire

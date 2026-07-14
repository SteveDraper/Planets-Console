"""Unit tests for compute concurrency timeline ring buffer and pairing."""

from __future__ import annotations

import time

from api.compute.diagnostics.timeline import (
    ComputeConcurrencyTimeline,
    OccupancyGauges,
    OpenExecutionTracker,
    format_execution_key,
    make_concurrency_event,
)


def _gauges(**overrides: int) -> OccupancyGauges:
    base = OccupancyGauges(
        scoped_ready_depth=0,
        scoped_in_flight_count=0,
        global_in_flight_count=0,
        global_queue_depth=0,
        configured_workers=4,
    )
    if not overrides:
        return base
    return OccupancyGauges(
        scoped_ready_depth=overrides.get("scoped_ready_depth", base.scoped_ready_depth),
        scoped_in_flight_count=overrides.get("scoped_in_flight_count", base.scoped_in_flight_count),
        global_in_flight_count=overrides.get("global_in_flight_count", base.global_in_flight_count),
        global_queue_depth=overrides.get("global_queue_depth", base.global_queue_depth),
        configured_workers=overrides.get("configured_workers", base.configured_workers),
    )


def test_timeline_ring_drops_oldest_on_wrap():
    timeline = ComputeConcurrencyTimeline(capacity=3)
    for index in range(5):
        timeline.append(
            make_concurrency_event(
                kind="ready",
                scope_key=f"scope-{index}",
                execution_key=f"key-{index}",
                gauges=_gauges(),
                step_kind="step",
                step_index=0,
            )
        )
    recent = timeline.recent()
    assert len(recent) == 3
    assert [event.scope_key for event in recent] == ["scope-2", "scope-3", "scope-4"]


def test_open_execution_tracker_pairs_duration_and_backend():
    tracker = OpenExecutionTracker()
    key = format_execution_key(
        orchestrator_id=1,
        scope_key="g1/p1/t1/pl1/scores",
        step_kind="materialize",
        step_index=0,
    )
    tracker.open(key, backend="thread")
    time.sleep(0.01)
    duration_ms, backend = tracker.close(key)
    assert backend == "thread"
    assert duration_ms is not None
    assert duration_ms >= 10.0
    assert tracker.close(key) == (None, None)


def test_make_concurrency_event_carries_gauges():
    event = make_concurrency_event(
        kind="start",
        scope_key="scope",
        execution_key="exec",
        gauges=_gauges(scoped_ready_depth=2, global_in_flight_count=3, configured_workers=8),
        step_kind="tier_solve",
        step_index=1,
        priority_band="background",
        backend="thread",
    )
    assert event.kind == "start"
    assert event.gauges.scoped_ready_depth == 2
    assert event.gauges.global_in_flight_count == 3
    assert event.gauges.configured_workers == 8
    assert event.backend == "thread"

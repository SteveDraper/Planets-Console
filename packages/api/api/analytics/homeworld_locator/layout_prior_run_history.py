"""Process-wide ring buffer of layout-prior solver run reports (#274)."""

from __future__ import annotations

import threading
from collections import deque

from api.analytics.homeworld_locator.layout_prior_report import (
    LAYOUT_PRIOR_REPORT_RING_CAPACITY,
    LayoutPriorSolverRunReport,
    layout_prior_report_to_wire,
)

_lock = threading.Lock()
_buffer: deque[LayoutPriorSolverRunReport] | None = None


def _get_buffer() -> deque[LayoutPriorSolverRunReport]:
    global _buffer
    if _buffer is None:
        _buffer = deque(maxlen=LAYOUT_PRIOR_REPORT_RING_CAPACITY)
    return _buffer


def record_layout_prior_report(report: LayoutPriorSolverRunReport) -> None:
    """Append a finished solver run (called only when the solver actually ran)."""
    with _lock:
        _get_buffer().append(report)


def recent_layout_prior_reports(
    *,
    game_id: int | None = None,
    perspective: int | None = None,
    turn: int | None = None,
) -> tuple[LayoutPriorSolverRunReport, ...]:
    """Newest-first reports, optionally filtered to one shell context."""
    with _lock:
        items = list(_get_buffer())
    items.reverse()
    if game_id is None and perspective is None and turn is None:
        return tuple(items)
    filtered: list[LayoutPriorSolverRunReport] = []
    for report in items:
        if game_id is not None and report.game_id != game_id:
            continue
        if perspective is not None and report.perspective != perspective:
            continue
        if turn is not None and report.turn != turn:
            continue
        filtered.append(report)
    return tuple(filtered)


def recent_layout_prior_reports_wire(
    *,
    game_id: int | None = None,
    perspective: int | None = None,
    turn: int | None = None,
) -> list[dict]:
    """Wire-shaped newest-first reports for BFF/SPA."""
    return [
        layout_prior_report_to_wire(report)
        for report in recent_layout_prior_reports(
            game_id=game_id, perspective=perspective, turn=turn
        )
    ]


def clear_layout_prior_reports() -> None:
    """Empty the process ring (tests)."""
    with _lock:
        _get_buffer().clear()


def reset_layout_prior_report_history_for_tests() -> None:
    """Drop the singleton buffer so capacity/constants can change in tests."""
    global _buffer
    with _lock:
        _buffer = None

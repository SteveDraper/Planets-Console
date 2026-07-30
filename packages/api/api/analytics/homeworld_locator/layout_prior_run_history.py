"""Process-wide ring buffer of layout-prior solver run reports (#274)."""

from __future__ import annotations

from api.analytics.homeworld_locator.layout_prior_report import (
    LAYOUT_PRIOR_REPORT_RING_CAPACITY,
    LayoutPriorSolverRunReport,
    layout_prior_report_to_wire,
)
from api.analytics.homeworld_locator.report_ring import ReportRing

_report_ring: ReportRing[LayoutPriorSolverRunReport] = ReportRing(
    capacity=LAYOUT_PRIOR_REPORT_RING_CAPACITY
)


def record_layout_prior_report(report: LayoutPriorSolverRunReport) -> None:
    """Append a finished solver run (called only when the solver actually ran)."""
    _report_ring.record(report)


def recent_layout_prior_reports(
    *,
    game_id: int | None = None,
    perspective: int | None = None,
    turn: int | None = None,
) -> tuple[LayoutPriorSolverRunReport, ...]:
    """Newest-first reports, optionally filtered to one shell context."""
    reports = _report_ring.recent(game_id=game_id, perspective=perspective)
    if turn is None:
        return reports
    return tuple(report for report in reports if report.turn == turn)


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
    _report_ring.clear()


def reset_layout_prior_report_history_for_tests() -> None:
    """Fixture entry point that returns the process ring to its empty state."""
    clear_layout_prior_reports()

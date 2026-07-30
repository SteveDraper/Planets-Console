"""Shared report-ring semantics: newest-first reads, shell filters, retention."""

from __future__ import annotations

from dataclasses import dataclass

from api.analytics.homeworld_locator.report_ring import ReportRing


@dataclass(frozen=True)
class _StubReport:
    game_id: int
    perspective: int
    label: str


def _ring_of(*reports: _StubReport, capacity: int = 8) -> ReportRing[_StubReport]:
    ring: ReportRing[_StubReport] = ReportRing(capacity=capacity)
    for report in reports:
        ring.record(report)
    return ring


def test_recent_returns_newest_first() -> None:
    ring = _ring_of(
        _StubReport(game_id=1, perspective=2, label="first"),
        _StubReport(game_id=1, perspective=2, label="second"),
    )
    assert [report.label for report in ring.recent()] == ["second", "first"]


def test_recent_filters_by_game_and_perspective() -> None:
    ring = _ring_of(
        _StubReport(game_id=1, perspective=2, label="match"),
        _StubReport(game_id=1, perspective=3, label="other_perspective"),
        _StubReport(game_id=9, perspective=2, label="other_game"),
    )
    assert [report.label for report in ring.recent(game_id=1)] == [
        "other_perspective",
        "match",
    ]
    assert [report.label for report in ring.recent(perspective=2)] == [
        "other_game",
        "match",
    ]
    assert [report.label for report in ring.recent(game_id=1, perspective=2)] == ["match"]
    assert ring.recent(game_id=4, perspective=2) == ()


def test_recent_retains_only_last_capacity_reports() -> None:
    ring = _ring_of(
        *(_StubReport(game_id=1, perspective=2, label=str(index)) for index in range(5)),
        capacity=3,
    )
    assert [report.label for report in ring.recent()] == ["4", "3", "2"]


def test_clear_empties_the_ring() -> None:
    ring = _ring_of(_StubReport(game_id=1, perspective=2, label="only"))
    ring.clear()
    assert ring.recent() == ()

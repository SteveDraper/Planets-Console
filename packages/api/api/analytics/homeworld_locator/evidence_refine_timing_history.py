"""Process-wide rings for homeworld evidence-refine and baseline timing reports."""

from __future__ import annotations

from api.analytics.homeworld_locator.evidence_refine_report import (
    BASELINE_REPORT_RING_CAPACITY,
    ENSURE_FAILURE_REPORT_RING_CAPACITY,
    EVIDENCE_REFINE_REPORT_RING_CAPACITY,
    BaselineRunReport,
    EnsureFailureReport,
    EvidenceRefineRunReport,
    baseline_report_to_wire,
    ensure_failure_report_to_wire,
    evidence_refine_report_to_wire,
    summarize_evidence_refine_reports,
)
from api.analytics.homeworld_locator.report_ring import ReportRing

_refine_ring: ReportRing[EvidenceRefineRunReport] = ReportRing(
    capacity=EVIDENCE_REFINE_REPORT_RING_CAPACITY
)
_baseline_ring: ReportRing[BaselineRunReport] = ReportRing(capacity=BASELINE_REPORT_RING_CAPACITY)
_ensure_failure_ring: ReportRing[EnsureFailureReport] = ReportRing(
    capacity=ENSURE_FAILURE_REPORT_RING_CAPACITY
)


def record_evidence_refine_report(report: EvidenceRefineRunReport) -> None:
    _refine_ring.record(report)


def record_baseline_report(report: BaselineRunReport) -> None:
    _baseline_ring.record(report)


def record_ensure_failure_report(report: EnsureFailureReport) -> None:
    _ensure_failure_ring.record(report)


def recent_evidence_refine_reports(
    *,
    game_id: int | None = None,
    perspective: int | None = None,
) -> tuple[EvidenceRefineRunReport, ...]:
    """Newest-first refine reports; filter by game/perspective (all turns)."""
    return _refine_ring.recent(game_id=game_id, perspective=perspective)


def recent_baseline_reports(
    *,
    game_id: int | None = None,
    perspective: int | None = None,
) -> tuple[BaselineRunReport, ...]:
    return _baseline_ring.recent(game_id=game_id, perspective=perspective)


def recent_ensure_failure_reports(
    *,
    game_id: int | None = None,
    perspective: int | None = None,
) -> tuple[EnsureFailureReport, ...]:
    return _ensure_failure_ring.recent(game_id=game_id, perspective=perspective)


def recent_evidence_refine_reports_wire(
    *,
    game_id: int | None = None,
    perspective: int | None = None,
) -> list[dict]:
    return [
        evidence_refine_report_to_wire(report)
        for report in recent_evidence_refine_reports(game_id=game_id, perspective=perspective)
    ]


def recent_baseline_reports_wire(
    *,
    game_id: int | None = None,
    perspective: int | None = None,
) -> list[dict]:
    return [
        baseline_report_to_wire(report)
        for report in recent_baseline_reports(game_id=game_id, perspective=perspective)
    ]


def recent_ensure_failure_reports_wire(
    *,
    game_id: int | None = None,
    perspective: int | None = None,
) -> list[dict]:
    return [
        ensure_failure_report_to_wire(report)
        for report in recent_ensure_failure_reports(game_id=game_id, perspective=perspective)
    ]


def evidence_refine_summary_wire(
    *,
    game_id: int,
    perspective: int,
) -> dict:
    return summarize_evidence_refine_reports(
        recent_evidence_refine_reports(game_id=game_id, perspective=perspective)
    )


def clear_evidence_refine_reports() -> None:
    _refine_ring.clear()


def clear_baseline_reports() -> None:
    _baseline_ring.clear()


def clear_ensure_failure_reports() -> None:
    _ensure_failure_ring.clear()


def reset_evidence_refine_report_history_for_tests() -> None:
    """Fixture entry point that returns all timing rings to their empty state."""
    clear_evidence_refine_reports()
    clear_baseline_reports()
    clear_ensure_failure_reports()

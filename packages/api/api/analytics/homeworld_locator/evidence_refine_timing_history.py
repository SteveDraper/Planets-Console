"""Process-wide rings for homeworld evidence-refine and baseline timing reports."""

from __future__ import annotations

import threading
from collections import deque

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

_refine_lock = threading.Lock()
_baseline_lock = threading.Lock()
_ensure_failure_lock = threading.Lock()
_refine_buffer: deque[EvidenceRefineRunReport] | None = None
_baseline_buffer: deque[BaselineRunReport] | None = None
_ensure_failure_buffer: deque[EnsureFailureReport] | None = None


def _get_refine_buffer() -> deque[EvidenceRefineRunReport]:
    global _refine_buffer
    if _refine_buffer is None:
        _refine_buffer = deque(maxlen=EVIDENCE_REFINE_REPORT_RING_CAPACITY)
    return _refine_buffer


def _get_baseline_buffer() -> deque[BaselineRunReport]:
    global _baseline_buffer
    if _baseline_buffer is None:
        _baseline_buffer = deque(maxlen=BASELINE_REPORT_RING_CAPACITY)
    return _baseline_buffer


def _get_ensure_failure_buffer() -> deque[EnsureFailureReport]:
    global _ensure_failure_buffer
    if _ensure_failure_buffer is None:
        _ensure_failure_buffer = deque(maxlen=ENSURE_FAILURE_REPORT_RING_CAPACITY)
    return _ensure_failure_buffer


def record_evidence_refine_report(report: EvidenceRefineRunReport) -> None:
    with _refine_lock:
        _get_refine_buffer().append(report)


def record_baseline_report(report: BaselineRunReport) -> None:
    with _baseline_lock:
        _get_baseline_buffer().append(report)


def record_ensure_failure_report(report: EnsureFailureReport) -> None:
    with _ensure_failure_lock:
        _get_ensure_failure_buffer().append(report)


def recent_evidence_refine_reports(
    *,
    game_id: int | None = None,
    perspective: int | None = None,
) -> tuple[EvidenceRefineRunReport, ...]:
    """Newest-first refine reports; filter by game/perspective (all turns)."""
    with _refine_lock:
        items = list(_get_refine_buffer())
    items.reverse()
    if game_id is None and perspective is None:
        return tuple(items)
    filtered: list[EvidenceRefineRunReport] = []
    for report in items:
        if game_id is not None and report.game_id != game_id:
            continue
        if perspective is not None and report.perspective != perspective:
            continue
        filtered.append(report)
    return tuple(filtered)


def recent_baseline_reports(
    *,
    game_id: int | None = None,
    perspective: int | None = None,
) -> tuple[BaselineRunReport, ...]:
    with _baseline_lock:
        items = list(_get_baseline_buffer())
    items.reverse()
    if game_id is None and perspective is None:
        return tuple(items)
    filtered: list[BaselineRunReport] = []
    for report in items:
        if game_id is not None and report.game_id != game_id:
            continue
        if perspective is not None and report.perspective != perspective:
            continue
        filtered.append(report)
    return tuple(filtered)


def recent_ensure_failure_reports(
    *,
    game_id: int | None = None,
    perspective: int | None = None,
) -> tuple[EnsureFailureReport, ...]:
    with _ensure_failure_lock:
        items = list(_get_ensure_failure_buffer())
    items.reverse()
    if game_id is None and perspective is None:
        return tuple(items)
    filtered: list[EnsureFailureReport] = []
    for report in items:
        if game_id is not None and report.game_id != game_id:
            continue
        if perspective is not None and report.perspective != perspective:
            continue
        filtered.append(report)
    return tuple(filtered)


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
    with _refine_lock:
        _get_refine_buffer().clear()


def clear_baseline_reports() -> None:
    with _baseline_lock:
        _get_baseline_buffer().clear()


def clear_ensure_failure_reports() -> None:
    with _ensure_failure_lock:
        _get_ensure_failure_buffer().clear()


def reset_evidence_refine_report_history_for_tests() -> None:
    global _refine_buffer, _baseline_buffer, _ensure_failure_buffer
    with _refine_lock:
        _refine_buffer = None
    with _baseline_lock:
        _baseline_buffer = None
    with _ensure_failure_lock:
        _ensure_failure_buffer = None

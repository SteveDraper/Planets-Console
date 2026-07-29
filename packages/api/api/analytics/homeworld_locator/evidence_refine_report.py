"""Homeworld evidence-refine / baseline timing reports for diagnostics.

Homeworld-owned telemetry -- distinct from compute diagnostics and from
layout-prior solver reports. Used to attribute DAG-unwind cost per turn.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# Unwind can emit one report per turn; keep enough for dense late-shell loads.
EVIDENCE_REFINE_REPORT_RING_CAPACITY = 128
BASELINE_REPORT_RING_CAPACITY = 16
ENSURE_FAILURE_REPORT_RING_CAPACITY = 32


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class EvidenceRefineInnerTimingMs:
    """Wall time inside ``refine_homeworld_evidence_aggregate``."""

    origin_distance_ms: float
    single_starbase_ms: float
    observation_upsert_ms: float
    total_ms: float


@dataclass(frozen=True)
class EvidenceRefineOuterTimingMs:
    """Wall time around one refine ensure/compute step."""

    load_game_state_ms: float
    load_prior_ms: float
    refine_inner_ms: float
    persist_ms: float
    total_ms: float


@dataclass(frozen=True)
class EvidenceRefineCounts:
    ship_count: int
    candidate_count: int
    prior_observation_count: int
    origin_distance_matches: int
    new_observations_appended: int
    single_starbase_promotions: int


@dataclass(frozen=True)
class EvidenceRefineRunReport:
    """One computed refine step (skipped/durable probes do not emit)."""

    game_id: int
    turn: int
    perspective: int
    baseline_turn: int
    timing_inner: EvidenceRefineInnerTimingMs
    timing_outer: EvidenceRefineOuterTimingMs
    counts: EvidenceRefineCounts
    captured_at: str


@dataclass(frozen=True)
class BaselineRunReport:
    """One baseline ensure attempt (recompute or satisfaction short-circuit)."""

    game_id: int
    perspective: int
    baseline_turn: int
    recomputed: bool
    candidate_count: int
    infer_ms: float
    total_ms: float
    captured_at: str


@dataclass(frozen=True)
class EnsureFailureReport:
    """One homeworld ensure failure that blocked shell materialize."""

    game_id: int
    perspective: int
    shell_turn: int
    reason: str
    message: str
    missing_turn: int | None
    captured_at: str


def evidence_refine_report_to_wire(report: EvidenceRefineRunReport) -> dict[str, Any]:
    return {
        "gameId": report.game_id,
        "turn": report.turn,
        "perspective": report.perspective,
        "baselineTurn": report.baseline_turn,
        "capturedAt": report.captured_at,
        "timingInner": {
            "originDistanceMs": report.timing_inner.origin_distance_ms,
            "singleStarbaseMs": report.timing_inner.single_starbase_ms,
            "observationUpsertMs": report.timing_inner.observation_upsert_ms,
            "totalMs": report.timing_inner.total_ms,
        },
        "timingOuter": {
            "loadGameStateMs": report.timing_outer.load_game_state_ms,
            "loadPriorMs": report.timing_outer.load_prior_ms,
            "refineInnerMs": report.timing_outer.refine_inner_ms,
            "persistMs": report.timing_outer.persist_ms,
            "totalMs": report.timing_outer.total_ms,
        },
        "counts": {
            "shipCount": report.counts.ship_count,
            "candidateCount": report.counts.candidate_count,
            "priorObservationCount": report.counts.prior_observation_count,
            "originDistanceMatches": report.counts.origin_distance_matches,
            "newObservationsAppended": report.counts.new_observations_appended,
            "singleStarbasePromotions": report.counts.single_starbase_promotions,
        },
    }


def baseline_report_to_wire(report: BaselineRunReport) -> dict[str, Any]:
    return {
        "gameId": report.game_id,
        "perspective": report.perspective,
        "baselineTurn": report.baseline_turn,
        "recomputed": report.recomputed,
        "candidateCount": report.candidate_count,
        "inferMs": report.infer_ms,
        "totalMs": report.total_ms,
        "capturedAt": report.captured_at,
    }


def ensure_failure_report_to_wire(report: EnsureFailureReport) -> dict[str, Any]:
    return {
        "gameId": report.game_id,
        "perspective": report.perspective,
        "shellTurn": report.shell_turn,
        "reason": report.reason,
        "message": report.message,
        "missingTurn": report.missing_turn,
        "capturedAt": report.captured_at,
    }


def build_evidence_refine_report(
    *,
    game_id: int,
    turn: int,
    perspective: int,
    baseline_turn: int,
    timing_inner: EvidenceRefineInnerTimingMs,
    timing_outer: EvidenceRefineOuterTimingMs,
    counts: EvidenceRefineCounts,
    captured_at: str | None = None,
) -> EvidenceRefineRunReport:
    return EvidenceRefineRunReport(
        game_id=game_id,
        turn=turn,
        perspective=perspective,
        baseline_turn=baseline_turn,
        timing_inner=timing_inner,
        timing_outer=timing_outer,
        counts=counts,
        captured_at=captured_at if captured_at is not None else _utc_now_iso(),
    )


def build_baseline_report(
    *,
    game_id: int,
    perspective: int,
    baseline_turn: int,
    recomputed: bool,
    candidate_count: int,
    infer_ms: float,
    total_ms: float,
    captured_at: str | None = None,
) -> BaselineRunReport:
    return BaselineRunReport(
        game_id=game_id,
        perspective=perspective,
        baseline_turn=baseline_turn,
        recomputed=recomputed,
        candidate_count=candidate_count,
        infer_ms=infer_ms,
        total_ms=total_ms,
        captured_at=captured_at if captured_at is not None else _utc_now_iso(),
    )


def build_ensure_failure_report(
    *,
    game_id: int,
    perspective: int,
    shell_turn: int,
    reason: str,
    message: str,
    missing_turn: int | None = None,
    captured_at: str | None = None,
) -> EnsureFailureReport:
    return EnsureFailureReport(
        game_id=game_id,
        perspective=perspective,
        shell_turn=shell_turn,
        reason=reason,
        message=message,
        missing_turn=missing_turn,
        captured_at=captured_at if captured_at is not None else _utc_now_iso(),
    )


def summarize_evidence_refine_reports(
    reports: Sequence[EvidenceRefineRunReport],
) -> dict[str, Any]:
    """Roll up newest-first refine reports for SPA overview."""
    if not reports:
        return {
            "reportCount": 0,
            "turnCount": 0,
            "sumOuterTotalMs": 0.0,
            "sumOriginDistanceMs": 0.0,
            "sumSingleStarbaseMs": 0.0,
            "sumObservationUpsertMs": 0.0,
            "sumPersistMs": 0.0,
            "sumLoadPriorMs": 0.0,
            "maxOuterTotalMs": 0.0,
            "maxOuterTotalTurn": None,
        }
    turns = {report.turn for report in reports}
    sum_outer = sum(report.timing_outer.total_ms for report in reports)
    sum_od = sum(report.timing_inner.origin_distance_ms for report in reports)
    sum_sb = sum(report.timing_inner.single_starbase_ms for report in reports)
    sum_upsert = sum(report.timing_inner.observation_upsert_ms for report in reports)
    sum_persist = sum(report.timing_outer.persist_ms for report in reports)
    sum_prior = sum(report.timing_outer.load_prior_ms for report in reports)
    heaviest = max(reports, key=lambda report: report.timing_outer.total_ms)
    return {
        "reportCount": len(reports),
        "turnCount": len(turns),
        "sumOuterTotalMs": sum_outer,
        "sumOriginDistanceMs": sum_od,
        "sumSingleStarbaseMs": sum_sb,
        "sumObservationUpsertMs": sum_upsert,
        "sumPersistMs": sum_persist,
        "sumLoadPriorMs": sum_prior,
        "maxOuterTotalMs": heaviest.timing_outer.total_ms,
        "maxOuterTotalTurn": heaviest.turn,
    }

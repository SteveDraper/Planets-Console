"""Layout-prior solver run report types and wire shaping (#274).

Homeworld-owned telemetry -- distinct from analytic-agnostic compute diagnostics.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from api.analytics.homeworld_locator.constants import LAYOUT_PRIOR_ALGORITHM_VERSION

# Process ring + series bounds (code constants; not YAML in v1).
LAYOUT_PRIOR_REPORT_RING_CAPACITY = 32
LAYOUT_PRIOR_INCUMBENT_SERIES_MAX_POINTS = 64

LayoutPriorStopReason = Literal["deadline", "max_steps", "exhausted", "no_choices"]
LayoutPriorStopGateKind = Literal["deadline", "max_steps", "never"]
LayoutPriorSolverName = Literal["anneal", "enumerate"]


@dataclass(frozen=True)
class LayoutPriorStopGateInfo:
    kind: LayoutPriorStopGateKind
    budget_ms: int | None = None
    max_steps: int | None = None


@dataclass(frozen=True)
class LayoutPriorTimingMs:
    greedy_ms: float
    sa_ms: float
    refine_ms: float
    total_ms: float


@dataclass(frozen=True)
class LayoutPriorSearchStats:
    sa_steps_attempted: int
    sa_steps_accepted: int
    greedy_cost: float
    pre_refine_cost: float
    final_cost: float
    tie_key: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class LayoutPriorProblemSizeHints:
    choice_sector_count: int
    total_possibles: int
    stand_in_sector_count: int
    planet_count: int
    category: str | None


@dataclass(frozen=True)
class LayoutPriorIncumbentSample:
    step: int
    cost: float


@dataclass(frozen=True)
class LayoutPriorSolverRunReport:
    """One finished layout-prior solver run (materialize path only; no cache hits)."""

    game_id: int
    turn: int
    perspective: int
    algorithm_version: int
    solver: LayoutPriorSolverName
    stop_gate: LayoutPriorStopGateInfo
    stop_reason: LayoutPriorStopReason
    timing: LayoutPriorTimingMs
    search: LayoutPriorSearchStats
    problem_size: LayoutPriorProblemSizeHints
    incumbent_cost_series: tuple[LayoutPriorIncumbentSample, ...]
    captured_at: str


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def downsample_incumbent_series(
    samples: Sequence[tuple[int, float]],
    *,
    max_points: int = LAYOUT_PRIOR_INCUMBENT_SERIES_MAX_POINTS,
) -> tuple[LayoutPriorIncumbentSample, ...]:
    """Bound an anytime curve: keep endpoints and uniform mid samples."""
    if max_points <= 0 or not samples:
        return ()
    if len(samples) <= max_points:
        return tuple(LayoutPriorIncumbentSample(step=s, cost=c) for s, c in samples)
    if max_points == 1:
        step, cost = samples[-1]
        return (LayoutPriorIncumbentSample(step=step, cost=cost),)

    last_index = len(samples) - 1
    chosen: list[int] = []
    seen: set[int] = set()
    for i in range(max_points):
        index = round(i * last_index / (max_points - 1))
        if index in seen:
            continue
        seen.add(index)
        chosen.append(index)
    return tuple(LayoutPriorIncumbentSample(step=samples[i][0], cost=samples[i][1]) for i in chosen)


def problem_size_hints(
    *,
    choice_sector_count: int,
    total_possibles: int,
    stand_in_sector_count: int,
    planet_count: int,
    category: str | None,
) -> LayoutPriorProblemSizeHints:
    return LayoutPriorProblemSizeHints(
        choice_sector_count=choice_sector_count,
        total_possibles=total_possibles,
        stand_in_sector_count=stand_in_sector_count,
        planet_count=planet_count,
        category=category,
    )


def build_run_report(
    *,
    game_id: int,
    turn: int,
    perspective: int,
    solver: LayoutPriorSolverName,
    stop_gate: LayoutPriorStopGateInfo,
    stop_reason: LayoutPriorStopReason,
    timing: LayoutPriorTimingMs,
    search: LayoutPriorSearchStats,
    problem_size: LayoutPriorProblemSizeHints,
    incumbent_cost_series: Sequence[LayoutPriorIncumbentSample],
    algorithm_version: int = LAYOUT_PRIOR_ALGORITHM_VERSION,
    captured_at: str | None = None,
) -> LayoutPriorSolverRunReport:
    return LayoutPriorSolverRunReport(
        game_id=game_id,
        turn=turn,
        perspective=perspective,
        algorithm_version=algorithm_version,
        solver=solver,
        stop_gate=stop_gate,
        stop_reason=stop_reason,
        timing=timing,
        search=search,
        problem_size=problem_size,
        incumbent_cost_series=tuple(incumbent_cost_series),
        captured_at=captured_at if captured_at is not None else utc_now_iso(),
    )


def layout_prior_report_to_wire(report: LayoutPriorSolverRunReport) -> dict[str, Any]:
    """SPA/BFF-facing camelCase dict for one run report."""
    return {
        "gameId": report.game_id,
        "turn": report.turn,
        "perspective": report.perspective,
        "algorithmVersion": report.algorithm_version,
        "solver": report.solver,
        "capturedAt": report.captured_at,
        "stopGate": {
            "kind": report.stop_gate.kind,
            "budgetMs": report.stop_gate.budget_ms,
            "maxSteps": report.stop_gate.max_steps,
        },
        "stopReason": report.stop_reason,
        "timing": {
            "greedyMs": report.timing.greedy_ms,
            "saMs": report.timing.sa_ms,
            "refineMs": report.timing.refine_ms,
            "totalMs": report.timing.total_ms,
        },
        "search": {
            "saStepsAttempted": report.search.sa_steps_attempted,
            "saStepsAccepted": report.search.sa_steps_accepted,
            "greedyCost": report.search.greedy_cost,
            "preRefineCost": report.search.pre_refine_cost,
            "finalCost": report.search.final_cost,
            "tieKey": [list(pair) for pair in report.search.tie_key],
        },
        "problemSize": {
            "choiceSectorCount": report.problem_size.choice_sector_count,
            "totalPossibles": report.problem_size.total_possibles,
            "standInSectorCount": report.problem_size.stand_in_sector_count,
            "planetCount": report.problem_size.planet_count,
            "category": report.problem_size.category,
        },
        "incumbentCostSeries": [
            {"step": sample.step, "cost": sample.cost} for sample in report.incumbent_cost_series
        ],
    }

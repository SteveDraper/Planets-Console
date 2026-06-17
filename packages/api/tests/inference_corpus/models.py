"""Data types for the inference corpus harness."""

import statistics
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class CaseOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED_COMPLEXITY = "skipped_complexity"
    SKIPPED_INCOMPLETE_MULTI_VIEW = "skipped_incomplete_multi_view"
    SKIPPED_PENDING_SOLVER = "skipped_pending_solver"
    OUT_OF_SEARCH_SPACE = "out_of_search_space"
    RANKING_MISS = "ranking_miss"


INFERENCE_FAILURE_OUTCOMES = frozenset(
    {
        CaseOutcome.FAILED,
        CaseOutcome.OUT_OF_SEARCH_SPACE,
        CaseOutcome.RANKING_MISS,
    }
)


ComplexityLevel = Literal["minimal", "routine", "heavy", "adjunct"]
COMPLEXITY_ORDINAL: dict[ComplexityLevel, int] = {
    "minimal": 0,
    "routine": 1,
    "heavy": 2,
    "adjunct": 3,
}


@dataclass(frozen=True)
class DiscoveredCase:
    id: str
    game_id: int
    perspective: int
    host_turn: int


@dataclass(frozen=True)
class ManifestCase:
    id: str
    game_id: int
    perspective: int
    host_turn: int
    prior_turn_path: str
    score_turn_path: str
    player_id: int | None
    game_info_path: str | None
    complexity: ComplexityLevel | None
    tier: int
    expected_status: str
    require_top_k: bool
    expect_coverage: bool
    required_perspectives: tuple[int, ...]
    notes: str | None


@dataclass(frozen=True)
class CorpusCaseResult:
    case_id: str
    outcome: CaseOutcome
    status: str | None = None
    solution_count: int | None = None
    complexity: ComplexityLevel | None = None
    complexity_reasons: tuple[str, ...] = ()
    ground_truth_available: bool | None = None
    coverage_reason: str | None = None
    skip_reason: str | None = None
    failure_message: str | None = None
    ground_truth_rank: int | None = None
    top_k: int | None = None
    hard_ranking_miss: bool = False
    elapsed_seconds: float | None = None


def _format_elapsed_suffix(elapsed_seconds: float | None) -> str:
    if elapsed_seconds is None:
        return ""
    return f" elapsed={elapsed_seconds:.2f}s"


def _format_ranking_miss_line(result: CorpusCaseResult, *, prefix: str) -> str:
    return (
        f"  {prefix} {result.case_id}: {result.failure_message} "
        f"(rank={result.ground_truth_rank}, topK={result.top_k})"
        f"{_format_elapsed_suffix(result.elapsed_seconds)}"
    )


@dataclass
class CorpusReport:
    results: list[CorpusCaseResult] = field(default_factory=list)
    stopped_early: bool = False
    stop_reason: str | None = None

    @property
    def passed_count(self) -> int:
        return sum(1 for result in self.results if result.outcome == CaseOutcome.PASSED)

    @property
    def failed_count(self) -> int:
        return sum(1 for result in self.results if result.outcome == CaseOutcome.FAILED)

    @property
    def inference_failure_count(self) -> int:
        return sum(1 for result in self.results if result.outcome in INFERENCE_FAILURE_OUTCOMES)

    @property
    def skipped_complexity_count(self) -> int:
        return sum(1 for result in self.results if result.outcome == CaseOutcome.SKIPPED_COMPLEXITY)

    @property
    def hard_failures(self) -> list[CorpusCaseResult]:
        return [result for result in self.results if result.outcome == CaseOutcome.FAILED]

    @property
    def hard_ranking_misses(self) -> list[CorpusCaseResult]:
        return [result for result in self.results if result.hard_ranking_miss]

    @property
    def exit_code(self) -> int:
        if self.failed_count or self.hard_ranking_misses:
            return 1
        return 0

    def summary_lines(self) -> list[str]:
        buckets = dict.fromkeys(CaseOutcome, 0)
        for result in self.results:
            buckets[result.outcome] += 1
        lines = [
            f"inference corpus: {len(self.results)} case(s)",
            f"  passed={buckets[CaseOutcome.PASSED]} failed={buckets[CaseOutcome.FAILED]}",
            (
                "  skipped_complexity="
                f"{buckets[CaseOutcome.SKIPPED_COMPLEXITY]} "
                f"skipped_incomplete_multi_view="
                f"{buckets[CaseOutcome.SKIPPED_INCOMPLETE_MULTI_VIEW]} "
                f"skipped_pending_solver={buckets[CaseOutcome.SKIPPED_PENDING_SOLVER]} "
                f"out_of_search_space={buckets[CaseOutcome.OUT_OF_SEARCH_SPACE]} "
                f"ranking_miss={buckets[CaseOutcome.RANKING_MISS]}"
            ),
        ]
        elapsed = [
            result.elapsed_seconds for result in self.results if result.elapsed_seconds is not None
        ]
        if elapsed:
            mean_elapsed = statistics.mean(elapsed)
            p90_elapsed = statistics.quantiles(elapsed, n=10)[8]
            lines.append(
                f"  inference_elapsed_seconds: mean={mean_elapsed:.2f} p90={p90_elapsed:.2f} "
                f"(n={len(elapsed)})"
            )
        for result in self.hard_failures:
            lines.append(
                f"  FAIL {result.case_id}: {result.failure_message}"
                f"{_format_elapsed_suffix(result.elapsed_seconds)}"
            )
        for result in self.hard_ranking_misses:
            lines.append(_format_ranking_miss_line(result, prefix="RANKING_MISS"))
        ranking_misses = [
            result
            for result in self.results
            if result.outcome == CaseOutcome.RANKING_MISS and not result.hard_ranking_miss
        ]
        for result in ranking_misses:
            lines.append(_format_ranking_miss_line(result, prefix="ranking_miss"))
        if self.stopped_early and self.stop_reason is not None:
            lines.append(f"  stopped_early={self.stop_reason}")
        return lines

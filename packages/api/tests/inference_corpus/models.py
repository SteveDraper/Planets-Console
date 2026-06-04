"""Data types for the inference corpus harness."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class CaseOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED_COMPLEXITY = "skipped_complexity"
    SKIPPED_INCOMPLETE_MULTI_VIEW = "skipped_incomplete_multi_view"
    OUT_OF_SEARCH_SPACE = "out_of_search_space"
    RANKING_MISS = "ranking_miss"


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


@dataclass
class CorpusReport:
    results: list[CorpusCaseResult] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        return sum(1 for result in self.results if result.outcome == CaseOutcome.PASSED)

    @property
    def failed_count(self) -> int:
        return sum(1 for result in self.results if result.outcome == CaseOutcome.FAILED)

    @property
    def skipped_complexity_count(self) -> int:
        return sum(1 for result in self.results if result.outcome == CaseOutcome.SKIPPED_COMPLEXITY)

    @property
    def hard_failures(self) -> list[CorpusCaseResult]:
        return [result for result in self.results if result.outcome == CaseOutcome.FAILED]

    @property
    def exit_code(self) -> int:
        return 1 if self.failed_count else 0

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
                f"out_of_search_space={buckets[CaseOutcome.OUT_OF_SEARCH_SPACE]} "
                f"ranking_miss={buckets[CaseOutcome.RANKING_MISS]}"
            ),
        ]
        for result in self.hard_failures:
            lines.append(f"  FAIL {result.case_id}: {result.failure_message}")
        return lines

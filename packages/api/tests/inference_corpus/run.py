"""Run one inference corpus case through the production inference API."""

from pathlib import Path

from api.analytics.military_score_inference.analytic import infer_military_score_build
from api.analytics.military_score_inference.solver import STATUS_EXACT, STATUS_TIME_LIMITED
from api.models.player import Score

from tests.inference_corpus.fixtures import (
    assert_required_perspectives_present,
    load_turn_fixture,
)
from tests.inference_corpus.manifest import FIXTURES_ROOT, resolve_player_id
from tests.inference_corpus.models import (
    COMPLEXITY_ORDINAL,
    CaseOutcome,
    ComplexityLevel,
    CorpusCaseResult,
    ManifestCase,
)
from tests.inference_corpus.verify import verify_top_solution_hard_equalities

DEFAULT_MAX_COMPLEXITY: ComplexityLevel = "heavy"


def run_manifest_case(
    case: ManifestCase,
    *,
    fixtures_root: Path = FIXTURES_ROOT,
    max_complexity: ComplexityLevel = DEFAULT_MAX_COMPLEXITY,
    include_adjunct: bool = False,
) -> CorpusCaseResult:
    """Execute Tier 1 pipeline for one manifest case."""
    skip_reason = _complexity_skip_reason(
        case,
        max_complexity=max_complexity,
        include_adjunct=include_adjunct,
    )
    if skip_reason is not None:
        return CorpusCaseResult(
            case_id=case.id,
            outcome=CaseOutcome.SKIPPED_COMPLEXITY,
            complexity=case.complexity,
            skip_reason=skip_reason,
        )

    multi_view_reason = assert_required_perspectives_present(
        case.id,
        case.game_id,
        case.host_turn,
        case.host_turn + 1,
        case.required_perspectives,
        fixtures_root=fixtures_root,
    )
    if multi_view_reason is not None:
        return CorpusCaseResult(
            case_id=case.id,
            outcome=CaseOutcome.SKIPPED_INCOMPLETE_MULTI_VIEW,
            skip_reason=multi_view_reason,
        )

    if case.expect_coverage:
        return CorpusCaseResult(
            case_id=case.id,
            outcome=CaseOutcome.OUT_OF_SEARCH_SPACE,
            coverage_reason="ground_truth_unavailable",
            skip_reason="catalog coverage checks not implemented in harness v1",
        )

    try:
        score_turn = load_turn_fixture(case.score_turn_path, fixtures_root=fixtures_root)
        player_id = resolve_player_id(case, fixtures_root=fixtures_root)
        score = _score_for_player(score_turn.scores, player_id, case.id)
    except (OSError, ValueError, KeyError) as exc:
        return CorpusCaseResult(
            case_id=case.id,
            outcome=CaseOutcome.FAILED,
            failure_message=str(exc),
        )

    inference = infer_military_score_build(score, score_turn)
    status = inference.get("status")
    if not isinstance(status, str):
        return CorpusCaseResult(
            case_id=case.id,
            outcome=CaseOutcome.FAILED,
            failure_message="inference payload missing status",
        )

    solution_count_raw = inference.get("solutionCount", 0)
    solution_count = solution_count_raw if isinstance(solution_count_raw, int) else 0

    status_failure = _tier1_status_failure(
        case,
        status=status,
        solution_count=solution_count,
    )
    if status_failure is not None:
        return CorpusCaseResult(
            case_id=case.id,
            outcome=CaseOutcome.FAILED,
            status=status,
            solution_count=solution_count,
            complexity=case.complexity,
            failure_message=status_failure,
        )

    if status in {STATUS_EXACT, STATUS_TIME_LIMITED} and solution_count >= 1:
        verify_failure = verify_top_solution_hard_equalities(
            score=score,
            turn=score_turn,
            inference_payload=inference,
        )
        if verify_failure is not None:
            return CorpusCaseResult(
                case_id=case.id,
                outcome=CaseOutcome.FAILED,
                status=status,
                solution_count=solution_count,
                complexity=case.complexity,
                failure_message=verify_failure,
            )

    return CorpusCaseResult(
        case_id=case.id,
        outcome=CaseOutcome.PASSED,
        status=status,
        solution_count=solution_count,
        complexity=case.complexity,
    )


def _score_for_player(scores: list[Score], player_id: int, case_id: str) -> Score:
    for score in scores:
        if score.ownerid == player_id:
            return score
    raise ValueError(f"case {case_id}: no score row for playerId {player_id}")


def _complexity_skip_reason(
    case: ManifestCase,
    *,
    max_complexity: ComplexityLevel,
    include_adjunct: bool,
) -> str | None:
    if case.complexity is None:
        return None
    if case.complexity == "adjunct" and not include_adjunct:
        return "adjunct_disabled"
    case_level = COMPLEXITY_ORDINAL[case.complexity]
    cap_level = COMPLEXITY_ORDINAL[max_complexity]
    if case_level > cap_level:
        return f"above_max_complexity:{case.complexity}>{max_complexity}"
    return None


def _tier1_status_failure(
    case: ManifestCase,
    *,
    status: str,
    solution_count: int,
) -> str | None:
    expected = case.expected_status
    complexity = case.complexity or "minimal"

    if status == expected:
        if expected == "exact" and solution_count < 1:
            return "expected at least one solution for exact status"
        return None

    if (
        complexity == "heavy"
        and expected == "exact"
        and status == STATUS_TIME_LIMITED
        and solution_count >= 1
    ):
        return None

    return f"status {status!r} != expected {expected!r} (solutions={solution_count})"

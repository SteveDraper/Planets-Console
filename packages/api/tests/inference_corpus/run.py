"""Run one inference corpus case through the production inference API."""

from pathlib import Path

from api.analytics.military_score_inference.actions import build_action_catalog_from_turn
from api.analytics.military_score_inference.analytic import (
    build_inference_observation,
    run_inference_with_artifacts,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT, STATUS_TIME_LIMITED
from api.models.game import TurnInfo
from api.models.player import Score
from api.services.game_service import GameService
from api.services.store_service import StoreService
from api.services.turn_load_service import TurnLoadService

from tests.inference_corpus.catalog_coverage import resolve_coverage_for_case
from tests.inference_corpus.complexity import (
    MergedTurnInventory,
    classify_complexity,
    merge_turn_inventories,
)
from tests.inference_corpus.discovery import list_perspectives_with_turn_pair
from tests.inference_corpus.fixtures import (
    assert_required_perspectives_present,
    load_turn_fixture,
)
from tests.inference_corpus.ground_truth import extract_ground_truth_v1
from tests.inference_corpus.manifest import FIXTURES_ROOT, resolve_player_id
from tests.inference_corpus.models import (
    COMPLEXITY_ORDINAL,
    CaseOutcome,
    ComplexityLevel,
    CorpusCaseResult,
    DiscoveredCase,
    ManifestCase,
)
from tests.inference_corpus.storage_loader import resolve_player_id_for_case
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
        case.complexity,
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

    try:
        prior_turn = load_turn_fixture(case.prior_turn_path, fixtures_root=fixtures_root)
        score_turn = load_turn_fixture(case.score_turn_path, fixtures_root=fixtures_root)
        player_id = resolve_player_id(case, fixtures_root=fixtures_root)
    except (OSError, ValueError, KeyError) as exc:
        return CorpusCaseResult(
            case_id=case.id,
            outcome=CaseOutcome.FAILED,
            failure_message=str(exc),
        )

    merged = merge_turn_inventories(
        case_perspective_prior=prior_turn,
        case_perspective_score=score_turn,
        other_prior_turns=(),
        other_score_turns=(),
    )
    try:
        score = score_for_player(score_turn.scores, player_id, case.id)
    except ValueError as exc:
        return CorpusCaseResult(
            case_id=case.id,
            outcome=CaseOutcome.FAILED,
            failure_message=str(exc),
        )

    complexity, complexity_reasons = classify_complexity(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=player_id,
        score=score,
        merged=merged,
    )
    skip_reason = _complexity_skip_reason(
        complexity,
        max_complexity=max_complexity,
        include_adjunct=include_adjunct,
    )
    if skip_reason is not None:
        return CorpusCaseResult(
            case_id=case.id,
            outcome=CaseOutcome.SKIPPED_COMPLEXITY,
            complexity=complexity,
            complexity_reasons=complexity_reasons,
            skip_reason=skip_reason,
        )

    return _run_case_pipeline(
        case_id=case.id,
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=player_id,
        score=score,
        complexity=complexity,
        complexity_reasons=complexity_reasons,
        expected_status=case.expected_status,
        expect_coverage=case.expect_coverage,
    )


def run_discovered_case(
    case: DiscoveredCase,
    *,
    turn_load: TurnLoadService,
    game_service: GameService,
    store: StoreService,
    max_complexity: ComplexityLevel = DEFAULT_MAX_COMPLEXITY,
    include_adjunct: bool = False,
    expected_status: str = "exact",
    expect_coverage: bool = False,
) -> CorpusCaseResult:
    """Execute Tier 1 pipeline for one case discovered from local storage."""
    score_turn_number = case.host_turn + 1
    try:
        prior_turn = turn_load.get_turn_info(case.game_id, case.perspective, case.host_turn)
        score_turn = turn_load.get_turn_info(case.game_id, case.perspective, score_turn_number)
        player_id = resolve_player_id_for_case(game_service, case.game_id, case.perspective)
    except (OSError, ValueError, KeyError) as exc:
        return CorpusCaseResult(
            case_id=case.id,
            outcome=CaseOutcome.FAILED,
            failure_message=str(exc),
        )

    merged = merged_inventory_for_case(
        case,
        turn_load=turn_load,
        store=store,
        prior_turn=prior_turn,
        score_turn=score_turn,
    )
    try:
        score = score_for_player(score_turn.scores, player_id, case.id)
    except ValueError as exc:
        return CorpusCaseResult(
            case_id=case.id,
            outcome=CaseOutcome.FAILED,
            failure_message=str(exc),
        )

    complexity, complexity_reasons = classify_complexity(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=player_id,
        score=score,
        merged=merged,
    )
    skip_reason = _complexity_skip_reason(
        complexity,
        max_complexity=max_complexity,
        include_adjunct=include_adjunct,
    )
    if skip_reason is not None:
        return CorpusCaseResult(
            case_id=case.id,
            outcome=CaseOutcome.SKIPPED_COMPLEXITY,
            complexity=complexity,
            complexity_reasons=complexity_reasons,
            skip_reason=skip_reason,
        )

    return _run_case_pipeline(
        case_id=case.id,
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=player_id,
        score=score,
        complexity=complexity,
        complexity_reasons=complexity_reasons,
        expected_status=expected_status,
        expect_coverage=expect_coverage,
    )


def merged_inventory_for_case(
    case: DiscoveredCase,
    *,
    turn_load: TurnLoadService,
    store: StoreService,
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
) -> MergedTurnInventory:
    score_turn_number = case.host_turn + 1
    other_perspectives = [
        perspective
        for perspective in list_perspectives_with_turn_pair(
            store,
            game_id=case.game_id,
            host_turn=case.host_turn,
            score_turn=score_turn_number,
        )
        if perspective != case.perspective
    ]
    other_prior: list[TurnInfo] = []
    other_score: list[TurnInfo] = []
    for perspective in other_perspectives:
        other_prior.append(turn_load.get_turn_info(case.game_id, perspective, case.host_turn))
        other_score.append(turn_load.get_turn_info(case.game_id, perspective, score_turn_number))
    return merge_turn_inventories(
        case_perspective_prior=prior_turn,
        case_perspective_score=score_turn,
        other_prior_turns=tuple(other_prior),
        other_score_turns=tuple(other_score),
    )


def _run_case_pipeline(
    *,
    case_id: str,
    prior_turn: TurnInfo,
    score_turn: TurnInfo,
    player_id: int,
    score: Score,
    complexity: ComplexityLevel,
    complexity_reasons: tuple[str, ...],
    expected_status: str,
    expect_coverage: bool,
) -> CorpusCaseResult:
    extraction = extract_ground_truth_v1(
        prior_turn=prior_turn,
        score_turn=score_turn,
        player_id=player_id,
        score=score,
        complexity=complexity,
    )
    observation = build_inference_observation(score, score_turn)
    catalog = build_action_catalog_from_turn(observation, score_turn)
    coverage_block = resolve_coverage_for_case(
        extraction=extraction,
        ground_truth=extraction.ground_truth,
        catalog=catalog,
        complexity_reasons=complexity_reasons,
        expect_coverage=expect_coverage,
    )
    if coverage_block is not None and not coverage_block.in_search_space:
        return CorpusCaseResult(
            case_id=case_id,
            outcome=CaseOutcome.OUT_OF_SEARCH_SPACE,
            complexity=complexity,
            complexity_reasons=complexity_reasons,
            ground_truth_available=extraction.available,
            coverage_reason=coverage_block.coverage_reason,
        )

    return _run_tier1_for_loaded_case(
        case_id=case_id,
        score_turn=score_turn,
        player_id=player_id,
        score=score,
        complexity=complexity,
        complexity_reasons=complexity_reasons,
        expected_status=expected_status,
        ground_truth_available=extraction.available,
    )


def _run_tier1_for_loaded_case(
    *,
    case_id: str,
    score_turn: TurnInfo,
    player_id: int,
    score: Score,
    complexity: ComplexityLevel | None,
    complexity_reasons: tuple[str, ...],
    expected_status: str,
    ground_truth_available: bool | None = None,
) -> CorpusCaseResult:
    inference, observation, catalog = run_inference_with_artifacts(score, score_turn)
    status = inference.get("status")
    if not isinstance(status, str):
        return CorpusCaseResult(
            case_id=case_id,
            outcome=CaseOutcome.FAILED,
            failure_message="inference payload missing status",
            complexity=complexity,
            complexity_reasons=complexity_reasons,
            ground_truth_available=ground_truth_available,
        )

    solution_count_raw = inference.get("solutionCount", 0)
    solution_count = solution_count_raw if isinstance(solution_count_raw, int) else 0

    status_failure = _tier1_status_failure(
        expected_status=expected_status,
        complexity=complexity,
        status=status,
        solution_count=solution_count,
    )
    if status_failure is not None:
        return CorpusCaseResult(
            case_id=case_id,
            outcome=CaseOutcome.FAILED,
            status=status,
            solution_count=solution_count,
            complexity=complexity,
            complexity_reasons=complexity_reasons,
            ground_truth_available=ground_truth_available,
            failure_message=status_failure,
        )

    if status in {STATUS_EXACT, STATUS_TIME_LIMITED} and solution_count >= 1:
        if catalog is None:
            verify_failure = "constraint re-check requires catalog from inference run"
        else:
            verify_failure = verify_top_solution_hard_equalities(
                observation=observation,
                catalog=catalog,
                inference_payload=inference,
            )
        if verify_failure is not None:
            return CorpusCaseResult(
                case_id=case_id,
                outcome=CaseOutcome.FAILED,
                status=status,
                solution_count=solution_count,
                complexity=complexity,
                complexity_reasons=complexity_reasons,
                ground_truth_available=ground_truth_available,
                failure_message=verify_failure,
            )

    return CorpusCaseResult(
        case_id=case_id,
        outcome=CaseOutcome.PASSED,
        status=status,
        solution_count=solution_count,
        complexity=complexity,
        complexity_reasons=complexity_reasons,
        ground_truth_available=ground_truth_available,
    )


def score_for_player(scores: list[Score], player_id: int, case_id: str) -> Score:
    for score in scores:
        if score.ownerid == player_id:
            return score
    raise ValueError(f"case {case_id}: no score row for playerId {player_id}")


def _complexity_skip_reason(
    complexity: ComplexityLevel | None,
    *,
    max_complexity: ComplexityLevel,
    include_adjunct: bool,
) -> str | None:
    if complexity is None:
        return None
    if complexity == "adjunct" and not include_adjunct:
        return "adjunct_disabled"
    case_level = COMPLEXITY_ORDINAL[complexity]
    cap_level = COMPLEXITY_ORDINAL[max_complexity]
    if case_level > cap_level:
        return f"above_max_complexity:{complexity}>{max_complexity}"
    return None


def _tier1_status_failure(
    *,
    expected_status: str,
    complexity: ComplexityLevel | None,
    status: str,
    solution_count: int,
) -> str | None:
    if status == expected_status:
        if expected_status == "exact" and solution_count < 1:
            return "expected at least one solution for exact status"
        return None

    if (
        complexity == "heavy"
        and expected_status == "exact"
        and status == STATUS_TIME_LIMITED
        and solution_count >= 1
    ):
        return None

    return f"status {status!r} != expected {expected_status!r} (solutions={solution_count})"

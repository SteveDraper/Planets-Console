"""Run one inference corpus case through the production inference API."""

import time
from dataclasses import dataclass, replace
from pathlib import Path

from api.analytics.military_score_inference.accelerated_start import needs_accelerated_backfill
from api.analytics.military_score_inference.actions import (
    DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
    ActionCatalog,
    build_action_catalog_from_turn,
)
from api.analytics.military_score_inference.analytic import (
    build_inference_observation,
    run_inference_with_artifacts,
)
from api.analytics.military_score_inference.inference_target import (
    resolve_inference_target_for_host_turn,
)
from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.solver import STATUS_EXACT, STATUS_TIME_LIMITED
from api.models.game import TurnInfo
from api.models.player import Score
from api.services.game_service import GameService
from api.services.store_service import StoreService
from api.services.turn_load_service import TurnLoadService

from tests.inference_corpus.case_helpers import score_for_player
from tests.inference_corpus.catalog_coverage import (
    COVERAGE_REASON_GROUND_TRUTH_UNAVAILABLE,
    resolve_coverage_for_case,
)
from tests.inference_corpus.complexity import (
    classify_complexity,
    merge_turn_inventories,
    merged_inventory_for_case,
)
from tests.inference_corpus.discovery import list_perspectives_with_turn_pair
from tests.inference_corpus.fixtures import (
    assert_required_perspectives_present,
    load_manifest_ground_truth_turn_snapshots,
    load_turn_fixture,
)
from tests.inference_corpus.ground_truth import (
    defense_aggregate_counts_negative,
    extract_ground_truth_v1,
)
from tests.inference_corpus.manifest import FIXTURES_ROOT, resolve_player_id
from tests.inference_corpus.models import (
    COMPLEXITY_ORDINAL,
    CaseOutcome,
    ComplexityLevel,
    CorpusCaseResult,
    DiscoveredCase,
    ManifestCase,
)
from tests.inference_corpus.storage_loader import (
    load_ground_truth_turn_snapshots,
    resolve_player_id_for_case,
)
from tests.inference_corpus.tier2 import verify_tier2_compatibility
from tests.inference_corpus.verify import (
    check_ground_truth_in_top_k,
    verify_top_solution_hard_equalities,
)

DEFAULT_MAX_COMPLEXITY: ComplexityLevel = "heavy"
DEFAULT_TOP_K = 3


@dataclass(frozen=True)
class LoadedCorpusCase:
    """Turn data and run parameters shared by manifest and discovered cases."""

    case_id: str
    prior_turn: TurnInfo
    score_turn: TurnInfo
    player_id: int
    score: Score
    complexity: ComplexityLevel
    complexity_reasons: tuple[str, ...]
    expected_status: str
    expect_coverage: bool


@dataclass(frozen=True)
class _LoadedCasePipelineContext:
    extraction: object
    negative_defense_gt: bool
    observation: InferenceObservation
    catalog: ActionCatalog
    coverage_passed: bool


def _manifest_scoreboard_turn_loader(
    case: ManifestCase,
    *,
    fixtures_root: Path = FIXTURES_ROOT,
):
    """Load optional scoreboard turns from the fixture tree (accelerated backfill)."""

    def load_scoreboard_turn(turn_number: int) -> TurnInfo | None:
        relative = f"{case.game_id}/{case.perspective}/turns/{turn_number}.json"
        path = fixtures_root / relative
        if not path.is_file():
            return None
        return load_turn_fixture(relative, fixtures_root=fixtures_root)

    return load_scoreboard_turn


def run_manifest_case(
    case: ManifestCase,
    *,
    fixtures_root: Path = FIXTURES_ROOT,
    max_complexity: ComplexityLevel = DEFAULT_MAX_COMPLEXITY,
    include_adjunct: bool = False,
    top_k: int = DEFAULT_TOP_K,
    enable_tier2: bool = False,
    fail_on_ranking_miss: bool = False,
    case_time_limit_seconds: float | None = DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
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

    gt_prior_turn, gt_score_turn = load_manifest_ground_truth_turn_snapshots(
        case,
        player_id,
        fixtures_root=fixtures_root,
    )

    return run_loaded_case(
        LoadedCorpusCase(
            case_id=case.id,
            prior_turn=prior_turn,
            score_turn=score_turn,
            player_id=player_id,
            score=score,
            complexity=complexity,
            complexity_reasons=complexity_reasons,
            expected_status=case.expected_status,
            expect_coverage=case.expect_coverage,
        ),
        ground_truth_prior_turn=gt_prior_turn,
        ground_truth_score_turn=gt_score_turn,
        load_scoreboard_turn=_manifest_scoreboard_turn_loader(case, fixtures_root=fixtures_root),
        top_k=top_k,
        enable_tier2=enable_tier2 or case.tier >= 2,
        hard_ranking=case.require_top_k or fail_on_ranking_miss,
        case_time_limit_seconds=case_time_limit_seconds,
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
    top_k: int = DEFAULT_TOP_K,
    enable_tier2: bool = False,
    fail_on_ranking_miss: bool = False,
    case_time_limit_seconds: float | None = DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
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

    def load_scoreboard_turn(turn_number: int) -> TurnInfo | None:
        try:
            return turn_load.get_turn_info(case.game_id, case.perspective, turn_number)
        except OSError, ValueError, KeyError:
            return None

    game_info = game_service.get_game_info(case.game_id)
    gt_prior_turn, gt_score_turn = load_ground_truth_turn_snapshots(
        turn_load,
        game_info,
        case.game_id,
        player_id,
        case.host_turn,
    )

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
    tier2_other_prior: list[TurnInfo] = []
    tier2_other_score: list[TurnInfo] = []
    for perspective in other_perspectives:
        try:
            tier2_other_prior.append(
                turn_load.get_turn_info(case.game_id, perspective, case.host_turn)
            )
            tier2_other_score.append(
                turn_load.get_turn_info(case.game_id, perspective, score_turn_number)
            )
        except OSError, ValueError, KeyError:
            continue

    return run_loaded_case(
        LoadedCorpusCase(
            case_id=case.id,
            prior_turn=prior_turn,
            score_turn=score_turn,
            player_id=player_id,
            score=score,
            complexity=complexity,
            complexity_reasons=complexity_reasons,
            expected_status=expected_status,
            expect_coverage=expect_coverage,
        ),
        load_scoreboard_turn=load_scoreboard_turn,
        ground_truth_prior_turn=gt_prior_turn,
        ground_truth_score_turn=gt_score_turn,
        top_k=top_k,
        enable_tier2=enable_tier2,
        hard_ranking=fail_on_ranking_miss,
        tier2_other_prior_turns=tuple(tier2_other_prior),
        tier2_other_score_turns=tuple(tier2_other_score),
        case_time_limit_seconds=case_time_limit_seconds,
    )


def run_loaded_case(
    loaded: LoadedCorpusCase,
    *,
    ground_truth_prior_turn: TurnInfo,
    ground_truth_score_turn: TurnInfo,
    load_scoreboard_turn=None,
    top_k: int = DEFAULT_TOP_K,
    enable_tier2: bool = False,
    hard_ranking: bool = False,
    tier2_other_prior_turns: tuple[TurnInfo, ...] = (),
    tier2_other_score_turns: tuple[TurnInfo, ...] = (),
    case_time_limit_seconds: float | None = DEFAULT_INFERENCE_TIME_LIMIT_SECONDS,
) -> CorpusCaseResult:
    """Ground truth, coverage, and Tier 1 on one observation and catalog build."""
    pipeline = _build_loaded_case_pipeline_context(
        loaded,
        ground_truth_prior_turn=ground_truth_prior_turn,
        ground_truth_score_turn=ground_truth_score_turn,
        load_scoreboard_turn=load_scoreboard_turn,
        enable_tier2=enable_tier2,
        tier2_other_prior_turns=tier2_other_prior_turns,
        tier2_other_score_turns=tier2_other_score_turns,
    )
    if isinstance(pipeline, CorpusCaseResult):
        return pipeline

    tier1_result, inference_payload = _run_tier1_for_loaded_case(
        case_id=loaded.case_id,
        score_turn=loaded.score_turn,
        score=loaded.score,
        complexity=loaded.complexity,
        complexity_reasons=loaded.complexity_reasons,
        expected_status=loaded.expected_status,
        ground_truth_available=pipeline.extraction.available,
        observation=pipeline.observation,
        catalog=pipeline.catalog,
        load_scoreboard_turn=load_scoreboard_turn,
        case_time_limit_seconds=case_time_limit_seconds,
    )
    if tier1_result.outcome != CaseOutcome.PASSED:
        return tier1_result

    if pipeline.negative_defense_gt:
        return CorpusCaseResult(
            case_id=loaded.case_id,
            outcome=CaseOutcome.SKIPPED_PENDING_SOLVER,
            status=tier1_result.status,
            solution_count=tier1_result.solution_count,
            complexity=loaded.complexity,
            complexity_reasons=loaded.complexity_reasons,
            ground_truth_available=True,
            skip_reason="negative_defense_gt_pending_solver",
            elapsed_seconds=tier1_result.elapsed_seconds,
        )

    if not (
        pipeline.extraction.available
        and pipeline.coverage_passed
        and tier1_result.status == STATUS_EXACT
        and inference_payload is not None
    ):
        return tier1_result

    return _apply_ranking_check(
        tier1_result,
        ground_truth=pipeline.extraction.ground_truth,
        inference_payload=inference_payload,
        top_k=top_k,
        hard_ranking=hard_ranking,
    )


def _build_loaded_case_pipeline_context(
    loaded: LoadedCorpusCase,
    *,
    ground_truth_prior_turn: TurnInfo,
    ground_truth_score_turn: TurnInfo,
    load_scoreboard_turn,
    enable_tier2: bool,
    tier2_other_prior_turns: tuple[TurnInfo, ...],
    tier2_other_score_turns: tuple[TurnInfo, ...],
) -> _LoadedCasePipelineContext | CorpusCaseResult:
    extraction = extract_ground_truth_v1(
        prior_turn=ground_truth_prior_turn,
        score_turn=ground_truth_score_turn,
        player_id=loaded.player_id,
        score=loaded.score,
        complexity=loaded.complexity,
    )
    negative_defense_gt = extraction.available and defense_aggregate_counts_negative(
        extraction.ground_truth
    )
    host_turn = loaded.score_turn.settings.turn - 1
    resolved = resolve_inference_target_for_host_turn(
        loaded.score,
        loaded.score_turn,
        host_turn=host_turn,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    if resolved is not None:
        observation = resolved.observation
        catalog_turn = resolved.turn_info
    else:
        observation = build_inference_observation(loaded.score, loaded.score_turn)
        catalog_turn = loaded.score_turn

    catalog = build_action_catalog_from_turn(observation, catalog_turn)
    coverage_passed = True
    if not negative_defense_gt:
        coverage_failure = _validate_coverage_for_loaded_case(
            loaded,
            extraction=extraction,
            resolved=resolved,
            observation=observation,
            catalog=catalog,
            catalog_turn=catalog_turn,
        )
        if coverage_failure is not None:
            return coverage_failure

        skip_coverage = (
            extraction.available
            and resolved is None
            and needs_accelerated_backfill(
                loaded.score_turn.settings.turn,
                loaded.score_turn.settings,
            )
        )
        coverage_block = (
            None
            if skip_coverage
            else resolve_coverage_for_case(
                extraction=extraction,
                ground_truth=extraction.ground_truth,
                catalog=catalog,
                complexity_reasons=loaded.complexity_reasons,
                observation=observation,
                score_turn=catalog_turn,
            )
        )

        if coverage_block is not None and not coverage_block.in_search_space:
            return CorpusCaseResult(
                case_id=loaded.case_id,
                outcome=CaseOutcome.OUT_OF_SEARCH_SPACE,
                complexity=loaded.complexity,
                complexity_reasons=loaded.complexity_reasons,
                ground_truth_available=extraction.available,
                coverage_reason=coverage_block.coverage_reason,
            )
        coverage_passed = coverage_block is None or coverage_block.in_search_space

    if enable_tier2 and extraction.available and not negative_defense_gt:
        tier2_failure = verify_tier2_compatibility(
            ground_truth=extraction.ground_truth,
            prior_turn=ground_truth_prior_turn,
            score_turn=ground_truth_score_turn,
            player_id=loaded.player_id,
            score=loaded.score,
            complexity=loaded.complexity,
            other_prior_turns=tier2_other_prior_turns,
            other_score_turns=tier2_other_score_turns,
        )
        if tier2_failure is not None:
            return CorpusCaseResult(
                case_id=loaded.case_id,
                outcome=CaseOutcome.FAILED,
                complexity=loaded.complexity,
                complexity_reasons=loaded.complexity_reasons,
                ground_truth_available=True,
                coverage_reason=coverage_block.coverage_reason if coverage_block else None,
                failure_message=tier2_failure,
            )

    return _LoadedCasePipelineContext(
        extraction=extraction,
        negative_defense_gt=negative_defense_gt,
        observation=observation,
        catalog=catalog,
        coverage_passed=coverage_passed,
    )


def _validate_coverage_for_loaded_case(
    loaded: LoadedCorpusCase,
    *,
    extraction,
    resolved,
    observation: InferenceObservation,
    catalog: ActionCatalog,
    catalog_turn: TurnInfo,
) -> CorpusCaseResult | None:
    if not loaded.expect_coverage:
        return None
    if not extraction.available:
        return CorpusCaseResult(
            case_id=loaded.case_id,
            outcome=CaseOutcome.FAILED,
            complexity=loaded.complexity,
            complexity_reasons=loaded.complexity_reasons,
            ground_truth_available=False,
            coverage_reason=COVERAGE_REASON_GROUND_TRUTH_UNAVAILABLE,
            failure_message=(
                "expectCoverage requires ground truth in search space; "
                "groundTruthAvailable is false"
            ),
        )

    skip_coverage = resolved is None and needs_accelerated_backfill(
        loaded.score_turn.settings.turn, loaded.score_turn.settings
    )
    if skip_coverage:
        return None

    coverage_block = resolve_coverage_for_case(
        extraction=extraction,
        ground_truth=extraction.ground_truth,
        catalog=catalog,
        complexity_reasons=loaded.complexity_reasons,
        observation=observation,
        score_turn=catalog_turn,
    )
    if coverage_block is None or coverage_block.in_search_space:
        return None

    return CorpusCaseResult(
        case_id=loaded.case_id,
        outcome=CaseOutcome.FAILED,
        complexity=loaded.complexity,
        complexity_reasons=loaded.complexity_reasons,
        ground_truth_available=True,
        coverage_reason=coverage_block.coverage_reason,
        failure_message=(
            f"expectCoverage requires in-search-space catalog coverage; "
            f"got {coverage_block.coverage_reason!r}"
        ),
    )


def _corpus_result_with_elapsed(
    result: CorpusCaseResult,
    elapsed_seconds: float,
) -> CorpusCaseResult:
    return replace(result, elapsed_seconds=elapsed_seconds)


def _run_tier1_for_loaded_case(
    *,
    case_id: str,
    score_turn: TurnInfo,
    score: Score,
    complexity: ComplexityLevel | None,
    complexity_reasons: tuple[str, ...],
    expected_status: str,
    ground_truth_available: bool | None = None,
    observation: InferenceObservation,
    catalog: ActionCatalog,
    load_scoreboard_turn=None,
    case_time_limit_seconds: float | None = None,
) -> tuple[CorpusCaseResult, dict[str, object] | None]:
    started_at = time.monotonic()
    inference, inference_observation, solve_catalog = run_inference_with_artifacts(
        score,
        score_turn,
        load_scoreboard_turn=load_scoreboard_turn,
        time_limit_seconds=case_time_limit_seconds,
    )
    elapsed_seconds = time.monotonic() - started_at
    status = inference.get("status")
    if not isinstance(status, str):
        return (
            _corpus_result_with_elapsed(
                CorpusCaseResult(
                    case_id=case_id,
                    outcome=CaseOutcome.FAILED,
                    failure_message="inference payload missing status",
                    complexity=complexity,
                    complexity_reasons=complexity_reasons,
                    ground_truth_available=ground_truth_available,
                ),
                elapsed_seconds,
            ),
            None,
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
        return (
            _corpus_result_with_elapsed(
                CorpusCaseResult(
                    case_id=case_id,
                    outcome=CaseOutcome.FAILED,
                    status=status,
                    solution_count=solution_count,
                    complexity=complexity,
                    complexity_reasons=complexity_reasons,
                    ground_truth_available=ground_truth_available,
                    failure_message=status_failure,
                ),
                elapsed_seconds,
            ),
            None,
        )

    if status in {STATUS_EXACT, STATUS_TIME_LIMITED} and solution_count >= 1:
        verify_failure = verify_top_solution_hard_equalities(
            observation=inference_observation,
            catalog=solve_catalog if solve_catalog is not None else catalog,
            inference_payload=inference,
        )
        if verify_failure is not None:
            return (
                _corpus_result_with_elapsed(
                    CorpusCaseResult(
                        case_id=case_id,
                        outcome=CaseOutcome.FAILED,
                        status=status,
                        solution_count=solution_count,
                        complexity=complexity,
                        complexity_reasons=complexity_reasons,
                        ground_truth_available=ground_truth_available,
                        failure_message=verify_failure,
                    ),
                    elapsed_seconds,
                ),
                None,
            )

    return (
        _corpus_result_with_elapsed(
            CorpusCaseResult(
                case_id=case_id,
                outcome=CaseOutcome.PASSED,
                status=status,
                solution_count=solution_count,
                complexity=complexity,
                complexity_reasons=complexity_reasons,
                ground_truth_available=ground_truth_available,
            ),
            elapsed_seconds,
        ),
        inference,
    )


def _apply_ranking_check(
    tier1_result: CorpusCaseResult,
    *,
    ground_truth: tuple[tuple[str, int], ...],
    inference_payload: dict[str, object],
    top_k: int,
    hard_ranking: bool,
) -> CorpusCaseResult:
    solutions = inference_payload.get("solutions")
    if not isinstance(solutions, list):
        return tier1_result

    hit, ground_truth_rank = check_ground_truth_in_top_k(
        ground_truth,
        solutions,
        k=top_k,
    )
    if hit:
        return tier1_result

    if ground_truth_rank is None:
        failure_message = f"ground truth not found in any of {len(solutions)} returned solution(s)"
    else:
        failure_message = f"ground truth at rank {ground_truth_rank} is outside top {top_k}"

    return CorpusCaseResult(
        case_id=tier1_result.case_id,
        outcome=CaseOutcome.RANKING_MISS,
        status=tier1_result.status,
        solution_count=tier1_result.solution_count,
        complexity=tier1_result.complexity,
        complexity_reasons=tier1_result.complexity_reasons,
        ground_truth_available=tier1_result.ground_truth_available,
        coverage_reason=tier1_result.coverage_reason,
        failure_message=failure_message,
        ground_truth_rank=ground_truth_rank,
        top_k=top_k,
        hard_ranking_miss=hard_ranking,
        elapsed_seconds=tier1_result.elapsed_seconds,
    )


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

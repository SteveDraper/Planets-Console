"""Ground-truth extraction, catalog build, coverage, and Tier 2 preflight for one loaded case."""

from dataclasses import dataclass

from api.analytics.military_score_inference.accelerated_start import needs_accelerated_backfill
from api.analytics.military_score_inference.actions import ActionCatalog, build_action_catalog_from_turn
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.inference_target import (
    resolve_inference_target_for_host_turn,
)
from api.analytics.military_score_inference.models import InferenceObservation
from api.models.game import TurnInfo
from api.models.player import Score

from tests.inference_corpus.catalog_coverage import (
    COVERAGE_REASON_GROUND_TRUTH_UNAVAILABLE,
    CatalogCoverageResult,
    resolve_coverage_for_case,
)
from tests.inference_corpus.ground_truth import (
    defense_aggregate_counts_negative,
    extract_ground_truth_v1,
)
from tests.inference_corpus.models import CaseOutcome, ComplexityLevel, CorpusCaseResult
from tests.inference_corpus.tier2 import verify_tier2_compatibility


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
class LoadedCasePipelineContext:
    extraction: object
    negative_defense_gt: bool
    observation: InferenceObservation
    catalog: ActionCatalog
    coverage_passed: bool


def build_loaded_case_pipeline_context(
    loaded: LoadedCorpusCase,
    *,
    ground_truth_prior_turn: TurnInfo,
    ground_truth_score_turn: TurnInfo,
    load_scoreboard_turn,
    enable_tier2: bool,
    tier2_other_prior_turns: tuple[TurnInfo, ...],
    tier2_other_score_turns: tuple[TurnInfo, ...],
) -> LoadedCasePipelineContext | CorpusCaseResult:
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
    coverage_block: CatalogCoverageResult | None = None
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

    return LoadedCasePipelineContext(
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

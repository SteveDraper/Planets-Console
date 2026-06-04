"""Catalog coverage gating for inference corpus ground truth (v1)."""

from dataclasses import dataclass

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.models import CandidateAction

from tests.inference_corpus.ground_truth import GroundTruth, GroundTruthExtraction

COVERAGE_REASON_GROUND_TRUTH_UNAVAILABLE = "ground_truth_unavailable"
COVERAGE_REASON_DEFERRED_TRADE = "deferred_trade"
COVERAGE_REASON_DEFERRED_SHIP_LOSS = "deferred_ship_loss"
COVERAGE_REASON_DEFERRED_STARBASE_LOSS = "deferred_starbase_loss"
COVERAGE_REASON_DEFERRED_PLANET_LOSS = "deferred_planet_loss"
COVERAGE_REASON_DEFERRED_MINEFIELD = "deferred_minefield"
COVERAGE_REASON_COMBO_NOT_IN_CATALOG = "combo_not_in_catalog"
COVERAGE_REASON_ACTION_NOT_IN_CATALOG = "action_not_in_catalog"
COVERAGE_REASON_COUNT_ABOVE_UPPER_BOUND = "count_above_upper_bound"

_COMPLEXITY_TO_COVERAGE: dict[str, str] = {
    "trade_or_capture_hint": COVERAGE_REASON_DEFERRED_TRADE,
    "net_ship_count_decrease": COVERAGE_REASON_DEFERRED_SHIP_LOSS,
    "planet_or_starbase_count_decrease": COVERAGE_REASON_DEFERRED_STARBASE_LOSS,
    "unexplained_military_change": COVERAGE_REASON_DEFERRED_MINEFIELD,
}


@dataclass(frozen=True)
class CatalogCoverageResult:
    in_search_space: bool
    coverage_reason: str | None = None


def coverage_reason_from_complexity(complexity_reasons: tuple[str, ...]) -> str | None:
    """Map complexity signals to stable coverageReason strings when effects are deferred."""
    for reason in complexity_reasons:
        coverage_reason = _COMPLEXITY_TO_COVERAGE.get(reason)
        if coverage_reason is not None:
            return coverage_reason
    return None


def evaluate_catalog_coverage(
    ground_truth: GroundTruth,
    catalog: ActionCatalog,
) -> CatalogCoverageResult:
    """Return whether every ground-truth tuple lies in the action catalog within bounds."""
    actions_by_id: dict[str, CandidateAction] = {action.id: action for action in catalog.actions}
    for action_id, count in ground_truth:
        catalog_action = actions_by_id.get(action_id)
        if catalog_action is None:
            if action_id.startswith("build_"):
                return CatalogCoverageResult(
                    in_search_space=False,
                    coverage_reason=COVERAGE_REASON_COMBO_NOT_IN_CATALOG,
                )
            return CatalogCoverageResult(
                in_search_space=False,
                coverage_reason=COVERAGE_REASON_ACTION_NOT_IN_CATALOG,
            )
        if count > catalog_action.upper_bound:
            return CatalogCoverageResult(
                in_search_space=False,
                coverage_reason=COVERAGE_REASON_COUNT_ABOVE_UPPER_BOUND,
            )
        if count < catalog_action.lower_bound:
            return CatalogCoverageResult(
                in_search_space=False,
                coverage_reason=COVERAGE_REASON_ACTION_NOT_IN_CATALOG,
            )
    return CatalogCoverageResult(in_search_space=True)


def resolve_coverage_for_case(
    *,
    extraction: GroundTruthExtraction,
    ground_truth: GroundTruth,
    catalog: ActionCatalog,
    complexity_reasons: tuple[str, ...],
    expect_coverage: bool,
) -> CatalogCoverageResult | None:
    """When coverage is required, return a failing result or None if the case may run Tier 1."""
    if not expect_coverage:
        return None

    deferred_reason = coverage_reason_from_complexity(complexity_reasons)
    if deferred_reason is not None:
        return CatalogCoverageResult(in_search_space=False, coverage_reason=deferred_reason)

    if not extraction.available:
        return CatalogCoverageResult(
            in_search_space=False,
            coverage_reason=COVERAGE_REASON_GROUND_TRUTH_UNAVAILABLE,
        )

    return evaluate_catalog_coverage(ground_truth, catalog)

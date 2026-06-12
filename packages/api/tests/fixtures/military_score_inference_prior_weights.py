"""Shared hull and catalog helpers for prior-weights catalog tests."""

from dataclasses import replace

from api.analytics.military_score_inference.aggregate_action_registry import (
    AGGREGATE_ACTION_SPECS,
    lookup_aggregate_action_spec,
)
from api.analytics.military_score_inference.hull_category import (
    BATTLESHIP_MASS_THRESHOLD,
    INFERENCE_HULL_CATEGORIES,
)
from api.analytics.military_score_inference.models import (
    ProbabilityBucket,
    probability_buckets_from_bin_bounds,
)
from api.analytics.military_score_inference.prior_weights_catalog import (
    CategoryComponentLogTables,
    PriorWeightsCatalog,
    PriorWeightsDiagnostics,
    ResolvedComponentCountTables,
)
from api.analytics.military_score_inference.prior_weights_laplace import (
    LEGACY_PARSIMONY_OCCURRENCE_PENALTY,
)
from api.models.components import Hull

# Active-bin marginal weights matching the pre-prior registry placeholders. The leading
# none-bin weight is derived (active max + occurrence penalty) so the gap from the none
# bin down to the most likely active bin reproduces the legacy parsimony penalty.
_STANDARD_TEST_ACTIVE_MARGINAL_WEIGHTS: dict[str, tuple[int, ...]] = {
    "planet_defense_posts_added_total": (100, 20, 5),
    "starbase_defense_posts_added_total": (100, 20, 5),
    "starbase_fighters_added_total": (80, 15, 3),
    "ship_fighters_added_total": (70, 20, 5),
    "ship_torps_loaded_1": (70, 70, 5),
    "ship_torps_loaded_2": (70, 70, 5),
    "ship_torps_loaded_3": (70, 70, 5),
    "fighters_starbase_to_ship": (15,),
    "fighters_ship_to_starbase": (10,),
}


def _with_none_bin_weight(active_weights: tuple[int, ...]) -> tuple[int, ...]:
    """Prepend the leading none-bin weight (active max + occurrence penalty)."""
    none_weight = max(active_weights) + LEGACY_PARSIMONY_OCCURRENCE_PENALTY
    return (none_weight, *active_weights)


STANDARD_TEST_HISTOGRAM_MARGINAL_WEIGHTS: dict[str, tuple[int, ...]] = {
    action_id: _with_none_bin_weight(active)
    for action_id, active in _STANDARD_TEST_ACTIVE_MARGINAL_WEIGHTS.items()
}


def probability_buckets_for_test_action(
    action_id: str,
    *,
    marginal_weights: tuple[int, ...] | None = None,
) -> tuple[ProbabilityBucket, ...]:
    spec = lookup_aggregate_action_spec(action_id)
    if spec is None:
        raise ValueError(f"action {action_id!r} has no solver bin bounds")
    weights = marginal_weights or STANDARD_TEST_HISTOGRAM_MARGINAL_WEIGHTS[action_id]
    return probability_buckets_from_bin_bounds(spec.bin_bounds, weights)


def complete_test_aggregate_bucket_weights() -> dict[str, tuple[int, ...]]:
    weights = dict(STANDARD_TEST_HISTOGRAM_MARGINAL_WEIGHTS)
    for action_id, spec in AGGREGATE_ACTION_SPECS.items():
        if action_id not in weights:
            active = tuple(10 for _ in spec.bin_bounds[1:])
            weights[action_id] = _with_none_bin_weight(active)
    return weights


def beam_ship_hull() -> Hull:
    return Hull(
        id=24,
        name="Serpent Class Escort",
        tritanium=33,
        duranium=15,
        molybdenum=5,
        fueltank=160,
        crew=35,
        engines=1,
        mass=55,
        techlevel=1,
        cargo=20,
        fighterbays=0,
        launchers=0,
        beams=2,
        cancloak=False,
        cost=40,
        special="",
        description="",
        advantage=0,
        isbase=False,
        dur=0,
        tri=0,
        mol=0,
        mc=0,
        parentid=0,
        academy=False,
    )


def torpedo_hull() -> Hull:
    return Hull(
        id=65,
        name="Torpedo Frigate",
        tritanium=20,
        duranium=10,
        molybdenum=5,
        fueltank=120,
        crew=40,
        engines=1,
        mass=80,
        techlevel=2,
        cargo=20,
        fighterbays=0,
        launchers=2,
        beams=1,
        cancloak=False,
        cost=50,
        special="",
        description="",
        advantage=0,
        isbase=False,
        dur=0,
        tri=0,
        mol=0,
        mc=0,
        parentid=0,
        academy=False,
    )


def battleship_hull() -> Hull:
    return replace(
        torpedo_hull(),
        id=90,
        name="Heavy Battleship",
        mass=BATTLESHIP_MASS_THRESHOLD + 50,
        beams=4,
        launchers=4,
    )


def _empty_component_table_shell() -> ResolvedComponentCountTables:
    return ResolvedComponentCountTables(
        engines={},
        beams={},
        torpedoes={},
        slot_fill={},
    )


def _empty_component_tables() -> CategoryComponentLogTables:
    return {category: _empty_component_table_shell() for category in INFERENCE_HULL_CATEGORIES}


def minimal_prior_catalog(
    *,
    hull_log_weights: dict[int, int] | None = None,
    combo_log_overrides: dict[str, int] | None = None,
    hull_log_overrides: dict[int, int] | None = None,
    aggregate_bucket_marginal_weights: dict[str, tuple[int, ...]] | None = None,
) -> PriorWeightsCatalog:
    return PriorWeightsCatalog(
        diagnostics=PriorWeightsDiagnostics(
            category_id="standard",
            asset_path="test",
            asset_version=1,
            game_category_rules_version=1,
            fell_back_to_standard=False,
            ship_limit_band="before_ship_limit",
            race_id_used=None,
        ),
        _hull_log_weights=hull_log_weights or {},
        _component_tables=_empty_component_tables(),
        _aggregate_bucket_marginal_weights=aggregate_bucket_marginal_weights
        or complete_test_aggregate_bucket_weights(),
        _combo_log_overrides=combo_log_overrides or {},
        _hull_log_overrides=hull_log_overrides or {},
    )

"""Resolve inference build prior catalogs from loaded assets."""

from __future__ import annotations

from pathlib import Path

from api.analytics.military_score_inference.aggregate_action_registry import (
    AggregateActionSlot,
    iter_aggregate_action_slots,
)
from api.analytics.military_score_inference.hull_category import (
    INFERENCE_HULL_CATEGORIES,
    InferenceHullCategory,
)
from api.analytics.military_score_inference.inference_game_category import (
    resolve_inference_game_category,
)
from api.analytics.military_score_inference.inference_probability_scale import (
    INFERENCE_PROBABILITY_WEIGHT_SCALE,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    ProbabilityBinBounds,
    magnitude_bin_index,
)
from api.analytics.military_score_inference.prior_weights_asset import (
    ComponentCountTables,
    HistogramAggregate,
    IntCountTableInput,
    PriorWeightsAsset,
    ShipLimitBand,
    load_prior_weights_for_category,
    lookup_slot_aggregate_prior,
)
from api.analytics.military_score_inference.prior_weights_catalog import (
    CategoryComponentLogTables,
    IntLogWeightTable,
    PriorWeightsCatalog,
    PriorWeightsDiagnostics,
    ResolvedComponentCountTables,
)
from api.analytics.military_score_inference.prior_weights_laplace import (
    IMPLICIT_UNIFORM_PSEUDO_COUNT,
    WILDCARD_COUNT_KEY,
    counts_to_log_weights,
    expand_wildcard_counts,
    finalize_counts_for_laplace,
    implicit_uniform_component_counts,
    none_bin_pseudo_count,
)
from api.models.game import GameSettings

_GENERIC_FREIGHTER_HULL_PRIOR_KEY = "generic_freighter"

__all__ = [
    "resolve_prior_weights_catalog",
    "ship_limit_band_key",
]


def ship_limit_band_key(observation: InferenceObservation) -> ShipLimitBand:
    if observation.is_after_ship_limit:
        return "after_ship_limit"
    return "before_ship_limit"


def _histogram_bucket_counts(
    histogram: dict[int, float],
    bin_bounds: tuple[ProbabilityBinBounds, ...],
) -> dict[int, float]:
    bucket_counts = dict.fromkeys(range(len(bin_bounds)), 0.0)
    for magnitude, count in histogram.items():
        bucket_counts[magnitude_bin_index(magnitude, bin_bounds)] += count
    return bucket_counts


def _resolve_hull_log_weights(
    asset: PriorWeightsAsset,
    *,
    band: ShipLimitBand,
    race_id: int | None,
    buildable_hull_ids: frozenset[int],
    generic_freighter_hull_ids: frozenset[int],
    scale: int,
) -> tuple[dict[int, int], int | None]:
    band_tables = asset.hulls.get(band, {})
    global_counts = band_tables.get("global", {})
    race_counts: IntCountTableInput = {}
    if race_id is not None:
        race_counts = band_tables.get(str(race_id), {})
    merged_counts = dict(global_counts)
    merged_counts.update(race_counts)
    expanded = expand_wildcard_counts(
        merged_counts,
        universe=buildable_hull_ids,
    )
    if WILDCARD_COUNT_KEY in expanded:
        if not buildable_hull_ids:
            expanded = {}
        else:
            raise ValueError(f"hulls.{band}: unresolved {WILDCARD_COUNT_KEY!r} after expansion")
    else:
        expanded = {
            hull_id: count
            for hull_id, count in expanded.items()
            if isinstance(hull_id, int) and hull_id in buildable_hull_ids
        }
    freighter_hull_ids = generic_freighter_hull_ids & frozenset(
        hull_id for hull_id in expanded if isinstance(hull_id, int)
    )
    generic_freighter_log_weight = None
    if freighter_hull_ids:
        freighter_count = sum(expanded[hull_id] for hull_id in freighter_hull_ids)
        solver_counts: dict[int | str, float] = {
            hull_id: count
            for hull_id, count in expanded.items()
            if hull_id not in freighter_hull_ids
        }
        solver_counts[_GENERIC_FREIGHTER_HULL_PRIOR_KEY] = freighter_count
        solver_log_weights = counts_to_log_weights(solver_counts, scale=scale)
        generic_freighter_log_weight = solver_log_weights.pop(_GENERIC_FREIGHTER_HULL_PRIOR_KEY)
        return {
            hull_id: weight
            for hull_id, weight in solver_log_weights.items()
            if isinstance(hull_id, int)
        }, generic_freighter_log_weight

    return counts_to_log_weights(finalize_counts_for_laplace(expanded), scale=scale), None


def _resolve_component_log_table(
    counts: IntCountTableInput,
    *,
    universe: frozenset[int],
    field_name: str,
    scale: int,
) -> IntLogWeightTable:
    expanded = expand_wildcard_counts(
        counts,
        universe=universe,
    )
    if WILDCARD_COUNT_KEY in expanded:
        raise ValueError(f"{field_name}: unresolved {WILDCARD_COUNT_KEY!r} after expansion")
    return counts_to_log_weights(finalize_counts_for_laplace(expanded), scale=scale)


def _implicit_uniform_component_log_table(
    universe: frozenset[int],
    *,
    scale: int,
) -> IntLogWeightTable:
    if not universe:
        return {}
    return counts_to_log_weights(implicit_uniform_component_counts(universe), scale=scale)


def _resolve_int_component_log_table(
    table_name: str,
    counts: IntCountTableInput | None,
    *,
    band: ShipLimitBand,
    category: InferenceHullCategory,
    universe: frozenset[int],
    scale: int,
) -> IntLogWeightTable:
    if counts is not None:
        return _resolve_component_log_table(
            counts,
            universe=universe,
            field_name=f"components.{band}.{category}.{table_name}",
            scale=scale,
        )
    return _implicit_uniform_component_log_table(universe, scale=scale)


def _resolve_category_component_tables(
    tables: ComponentCountTables | None,
    *,
    band: ShipLimitBand,
    category: InferenceHullCategory,
    universe_by_table: dict[str, frozenset[int]],
    scale: int,
) -> ResolvedComponentCountTables:
    asset_tables = tables or ComponentCountTables()
    slot_fill: dict[str, int] = {}
    if asset_tables.slot_fill is not None:
        slot_fill = counts_to_log_weights(asset_tables.slot_fill, scale=scale)
    return ResolvedComponentCountTables(
        engines=_resolve_int_component_log_table(
            "engines",
            asset_tables.engines,
            band=band,
            category=category,
            universe=universe_by_table["engines"],
            scale=scale,
        ),
        beams=_resolve_int_component_log_table(
            "beams",
            asset_tables.beams,
            band=band,
            category=category,
            universe=universe_by_table["beams"],
            scale=scale,
        ),
        torpedoes=_resolve_int_component_log_table(
            "torpedoes",
            asset_tables.torpedoes,
            band=band,
            category=category,
            universe=universe_by_table["torpedoes"],
            scale=scale,
        ),
        slot_fill=slot_fill,
    )


def _resolve_component_tables(
    asset: PriorWeightsAsset,
    *,
    band: ShipLimitBand,
    eligible_engine_ids: frozenset[int],
    eligible_beam_ids: frozenset[int],
    eligible_torp_ids: frozenset[int],
    scale: int,
) -> CategoryComponentLogTables:
    band_tables = asset.components.get(band, {})
    universe_by_table = {
        "engines": eligible_engine_ids,
        "beams": eligible_beam_ids,
        "torpedoes": eligible_torp_ids,
    }
    return {
        category: _resolve_category_component_tables(
            band_tables.get(category),
            band=band,
            category=category,
            universe_by_table=universe_by_table,
            scale=scale,
        )
        for category in INFERENCE_HULL_CATEGORIES
    }


def _implicit_uniform_histogram_bucket_weights(
    bin_bounds: tuple[ProbabilityBinBounds, ...],
    *,
    scale: int,
) -> tuple[int, ...]:
    # Seed active bins uniformly and the leading none bin so a missing asset table
    # still carries the ~LEGACY_PARSIMONY_OCCURRENCE_PENALTY occurrence cost instead
    # of becoming free.
    bucket_counts: dict[int, float] = {0: none_bin_pseudo_count(IMPLICIT_UNIFORM_PSEUDO_COUNT)}
    for index in range(1, len(bin_bounds)):
        bucket_counts[index] = IMPLICIT_UNIFORM_PSEUDO_COUNT
    log_weights = counts_to_log_weights(bucket_counts, scale=scale)
    return tuple(log_weights[index] for index in range(len(bin_bounds)))


def _resolve_histogram_aggregate_weights(
    aggregate: HistogramAggregate,
    bin_bounds: tuple[ProbabilityBinBounds, ...],
    *,
    scale: int,
) -> tuple[int, ...]:
    bucket_counts = _histogram_bucket_counts(aggregate.histogram, bin_bounds)
    log_weights = counts_to_log_weights(bucket_counts, scale=scale)
    return tuple(log_weights[index] for index in range(len(bin_bounds)))


def _resolve_slot_histogram_bucket_weights(
    slot: AggregateActionSlot,
    band_tables: dict[str, HistogramAggregate],
    *,
    band: ShipLimitBand,
    scale: int,
) -> tuple[int, ...]:
    bin_bounds = slot.spec.bin_bounds
    aggregate = lookup_slot_aggregate_prior(
        band_tables,
        band=band,
        action_id=slot.action_id,
        spec=slot.spec,
    )
    if aggregate is None:
        return _implicit_uniform_histogram_bucket_weights(bin_bounds, scale=scale)
    return _resolve_histogram_aggregate_weights(aggregate, bin_bounds, scale=scale)


def _resolve_aggregate_priors(
    asset: PriorWeightsAsset,
    *,
    band: ShipLimitBand,
    eligible_torp_ids: frozenset[int],
    scale: int,
) -> dict[str, tuple[int, ...]]:
    bucket_weights: dict[str, tuple[int, ...]] = {}
    band_tables = asset.aggregates.get(band, {})

    for slot in iter_aggregate_action_slots(eligible_torp_ids=eligible_torp_ids):
        bucket_weights[slot.action_id] = _resolve_slot_histogram_bucket_weights(
            slot,
            band_tables,
            band=band,
            scale=scale,
        )

    return bucket_weights


def resolve_prior_weights_catalog(
    observation: InferenceObservation,
    settings: GameSettings,
    *,
    race_id: int | None = None,
    buildable_hull_ids: frozenset[int],
    generic_freighter_hull_ids: frozenset[int] = frozenset(),
    eligible_engine_ids: frozenset[int],
    eligible_beam_ids: frozenset[int],
    eligible_torp_ids: frozenset[int],
    base_dir: Path | None = None,
    scale: int = INFERENCE_PROBABILITY_WEIGHT_SCALE,
) -> PriorWeightsCatalog:
    if not (buildable_hull_ids or eligible_engine_ids or eligible_beam_ids or eligible_torp_ids):
        raise ValueError(
            "resolve_prior_weights_catalog requires at least one non-empty eligibility "
            "universe (buildable_hull_ids, eligible_engine_ids, eligible_beam_ids, "
            "eligible_torp_ids)"
        )

    category_id = resolve_inference_game_category(settings)
    asset, asset_path, fell_back = load_prior_weights_for_category(
        category_id,
        base_dir=base_dir,
    )
    band = ship_limit_band_key(observation)

    hull_log_weights, generic_freighter_log_weight = _resolve_hull_log_weights(
        asset,
        band=band,
        race_id=race_id,
        buildable_hull_ids=buildable_hull_ids,
        generic_freighter_hull_ids=generic_freighter_hull_ids,
        scale=scale,
    )
    component_tables = _resolve_component_tables(
        asset,
        band=band,
        eligible_engine_ids=eligible_engine_ids,
        eligible_beam_ids=eligible_beam_ids,
        eligible_torp_ids=eligible_torp_ids,
        scale=scale,
    )
    aggregate_bucket_weights = _resolve_aggregate_priors(
        asset,
        band=band,
        eligible_torp_ids=eligible_torp_ids,
        scale=scale,
    )

    combo_log_overrides = counts_to_log_weights(asset.combo_overrides, scale=scale)
    hull_log_overrides_int = counts_to_log_weights(asset.hull_overrides, scale=scale)

    diagnostics = PriorWeightsDiagnostics(
        category_id=category_id,
        asset_path=str(asset_path),
        asset_version=asset.version,
        game_category_rules_version=asset.game_category_rules_version,
        fell_back_to_standard=fell_back,
        ship_limit_band=band,
        race_id_used=race_id,
    )

    return PriorWeightsCatalog(
        diagnostics=diagnostics,
        _hull_log_weights=hull_log_weights,
        _component_tables=component_tables,
        _aggregate_bucket_marginal_weights=aggregate_bucket_weights,
        _combo_log_overrides=combo_log_overrides,
        _hull_log_overrides=hull_log_overrides_int,
        _generic_freighter_log_weight=generic_freighter_log_weight,
    )

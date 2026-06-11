"""Resolve inference build prior catalogs from loaded assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from api.analytics.military_score_inference.aggregate_action_registry import (
    AggregateActionSlot,
    iter_aggregate_action_slots,
    lookup_aggregate_action_spec,
    magnitude_bin_index,
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
from api.analytics.military_score_inference.models import InferenceObservation, ProbabilityBinBounds
from api.analytics.military_score_inference.prior_weights_asset import (
    COMPONENT_TABLE_NAMES,
    AggregatePrior,
    ComponentCountTables,
    CountsAggregate,
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
    WILDCARD_COUNT_KEY,
    counts_to_log_weights,
    expand_wildcard_counts,
    finalize_counts_for_laplace,
    implicit_uniform_component_counts,
)
from api.models.game import GameSettings

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
    scale: int,
) -> dict[int, int]:
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
    if WILDCARD_COUNT_KEY in expanded and buildable_hull_ids:
        raise ValueError(f"hulls.{band}: unresolved {WILDCARD_COUNT_KEY!r} after expansion")
    return counts_to_log_weights(finalize_counts_for_laplace(expanded), scale=scale)


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


def _resolve_category_component_tables(
    tables: ComponentCountTables | None,
    *,
    band: ShipLimitBand,
    category: InferenceHullCategory,
    universe_by_table: dict[str, frozenset[int]],
    scale: int,
) -> ResolvedComponentCountTables:
    asset_tables = tables or {}
    resolved_tables: ResolvedComponentCountTables = {}
    for table_name, counts in asset_tables.items():
        if table_name == "slotFill":
            resolved_tables[table_name] = counts_to_log_weights(
                counts,
                scale=scale,
            )
            continue
        universe = universe_by_table.get(table_name, frozenset())
        resolved_tables[table_name] = _resolve_component_log_table(
            counts,
            universe=universe,
            field_name=f"components.{band}.{category}.{table_name}",
            scale=scale,
        )
    for table_name in COMPONENT_TABLE_NAMES:
        if table_name in resolved_tables:
            continue
        resolved_tables[table_name] = _implicit_uniform_component_log_table(
            universe_by_table[table_name],
            scale=scale,
        )
    return resolved_tables


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
    bucket_counts = implicit_uniform_component_counts(frozenset(range(len(bin_bounds))))
    log_weights = counts_to_log_weights(bucket_counts, scale=scale)
    return tuple(log_weights[index] for index in range(len(bin_bounds)))


def _resolve_histogram_aggregate_weights(
    aggregate: HistogramAggregate,
    action_id: str,
    *,
    band: ShipLimitBand,
    scale: int,
) -> tuple[int, ...]:
    spec = lookup_aggregate_action_spec(action_id)
    bin_bounds = spec.bin_bounds if spec is not None else None
    if bin_bounds is None:
        raise ValueError(f"aggregates.{band}.{action_id!r} has no solver bin definition")
    bucket_counts = _histogram_bucket_counts(aggregate.histogram, bin_bounds)
    log_weights = counts_to_log_weights(bucket_counts, scale=scale)
    return tuple(log_weights[index] for index in range(len(bin_bounds)))


def _resolve_counts_aggregate_weight(
    aggregate: CountsAggregate,
    *,
    scale: int,
) -> int:
    return counts_to_log_weights({"default": aggregate.pseudo_count}, scale=scale)["default"]


@dataclass(frozen=True)
class HistogramBucketWeights:
    weights: tuple[int, ...]


@dataclass(frozen=True)
class CountsPriorWeight:
    weight: int


ResolvedPrior = HistogramBucketWeights | CountsPriorWeight


def _resolve_slot_aggregate_prior(
    slot: AggregateActionSlot,
    band_tables: dict[str, AggregatePrior],
    *,
    band: ShipLimitBand,
    scale: int,
) -> ResolvedPrior:
    action_id = slot.action_id
    aggregate = lookup_slot_aggregate_prior(
        band_tables,
        band=band,
        action_id=action_id,
        spec=slot.spec,
    )
    if aggregate is None:
        bin_bounds = slot.spec.bin_bounds
        if bin_bounds is None:
            raise ValueError(f"aggregate action {action_id!r} has no solver bin definition")
        return HistogramBucketWeights(
            _implicit_uniform_histogram_bucket_weights(bin_bounds, scale=scale)
        )
    if isinstance(aggregate, HistogramAggregate):
        return HistogramBucketWeights(
            _resolve_histogram_aggregate_weights(
                aggregate,
                action_id,
                band=band,
                scale=scale,
            )
        )
    return CountsPriorWeight(_resolve_counts_aggregate_weight(aggregate, scale=scale))


def _resolve_aggregate_priors(
    asset: PriorWeightsAsset,
    *,
    band: ShipLimitBand,
    eligible_torp_ids: frozenset[int],
    scale: int,
) -> tuple[dict[str, int], dict[str, tuple[int, ...]]]:
    action_weights: dict[str, int] = {}
    bucket_weights: dict[str, tuple[int, ...]] = {}
    band_tables = asset.aggregates.get(band, {})

    for slot in iter_aggregate_action_slots(eligible_torp_ids=eligible_torp_ids):
        resolved = _resolve_slot_aggregate_prior(
            slot,
            band_tables,
            band=band,
            scale=scale,
        )
        if isinstance(resolved, HistogramBucketWeights):
            bucket_weights[slot.action_id] = resolved.weights
        else:
            action_weights[slot.action_id] = resolved.weight

    return action_weights, bucket_weights


def resolve_prior_weights_catalog(
    observation: InferenceObservation,
    settings: GameSettings,
    *,
    race_id: int | None = None,
    buildable_hull_ids: frozenset[int],
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

    hull_log_weights = _resolve_hull_log_weights(
        asset,
        band=band,
        race_id=race_id,
        buildable_hull_ids=buildable_hull_ids,
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
    aggregate_action_weights, aggregate_bucket_weights = _resolve_aggregate_priors(
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

    return PriorWeightsCatalog.from_resolved_tables(
        diagnostics=diagnostics,
        hull_log_weights=hull_log_weights,
        component_tables=component_tables,
        aggregate_action_weights=aggregate_action_weights,
        aggregate_bucket_marginal_weights=aggregate_bucket_weights,
        combo_log_overrides=combo_log_overrides,
        hull_log_overrides=hull_log_overrides_int,
    )

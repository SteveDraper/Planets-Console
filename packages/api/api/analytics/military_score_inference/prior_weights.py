"""Resolve inference build prior catalogs from loaded assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api.analytics.military_score_inference.aggregate_action_registry import (
    is_counts_aggregate_action,
    is_histogram_aggregate_action,
)
from api.analytics.military_score_inference.hull_category import (
    INFERENCE_HULL_CATEGORIES,
    InferenceHullCategory,
    resolve_inference_hull_category,
    slot_fill_pattern,
)
from api.analytics.military_score_inference.inference_game_category import (
    resolve_inference_game_category,
)
from api.analytics.military_score_inference.inference_probability_scale import (
    INFERENCE_PROBABILITY_WEIGHT_SCALE,
)
from api.analytics.military_score_inference.models import InferenceObservation, ProbabilityBucket
from api.analytics.military_score_inference.prior_weights_asset import (
    COMPONENT_TABLE_NAMES,
    CountsAggregate,
    HistogramAggregate,
    PriorWeightsAsset,
    ShipLimitBand,
    load_prior_weights_for_category,
)
from api.analytics.military_score_inference.prior_weights_laplace import (
    WILDCARD_COUNT_KEY,
    counts_to_log_weights,
    expand_wildcard_counts,
    finalize_counts_for_laplace,
    implicit_uniform_component_counts,
)
from api.analytics.military_score_inference.probability_bucket_defaults import (
    base_buckets_for_action,
    magnitude_bin_index,
)
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import GameSettings

__all__ = [
    "PriorWeightsCatalog",
    "PriorWeightsDiagnostics",
    "resolve_prior_weights_catalog",
    "ship_limit_band_key",
]


def ship_limit_band_key(observation: InferenceObservation) -> ShipLimitBand:
    if observation.is_after_ship_limit:
        return "after_ship_limit"
    return "before_ship_limit"


@dataclass(frozen=True)
class PriorWeightsDiagnostics:
    category_id: str
    asset_path: str
    asset_version: int
    game_category_rules_version: int
    fell_back_to_standard: bool
    ship_limit_band: ShipLimitBand
    race_id_used: int | None

    def to_payload(self) -> dict[str, object]:
        return {
            "categoryId": self.category_id,
            "assetPath": self.asset_path,
            "assetVersion": self.asset_version,
            "gameCategoryRulesVersion": self.game_category_rules_version,
            "fellBackToStandard": self.fell_back_to_standard,
            "shipLimitBand": self.ship_limit_band,
            "raceIdUsed": self.race_id_used,
        }


@dataclass(frozen=True)
class PriorWeightsCatalog:
    diagnostics: PriorWeightsDiagnostics
    hull_log_weights: dict[int, int]
    component_tables: dict[
        InferenceHullCategory,
        dict[str, dict[Any, int]],
    ]
    aggregate_action_weights: dict[str, int]
    aggregate_bucket_marginal_weights: dict[str, tuple[int, ...]]
    combo_log_overrides: dict[str, int]
    hull_log_overrides: dict[int, int]

    def _hull_marginal_log_weight(self, hull_id: int, *, default_weight: int = 0) -> int:
        hull_override = self.hull_log_overrides.get(hull_id)
        if hull_override is not None:
            return hull_override
        return self.hull_log_weights.get(hull_id, default_weight)

    def freighter_probability_weight(self, *, combo_id: str, default_weight: int) -> int:
        from api.analytics.military_score_inference.ship_build_combos import (
            GENERIC_FREIGHTER_PRIOR_HULL_ID,
        )

        override = self.combo_log_overrides.get(combo_id)
        if override is not None:
            return override
        return self._hull_marginal_log_weight(
            GENERIC_FREIGHTER_PRIOR_HULL_ID,
            default_weight=default_weight,
        )

    def combo_probability_weight(
        self,
        *,
        combo_id: str,
        hull: Hull,
        engine: Engine,
        beam: Beam | None,
        torpedo: Torpedo | None,
        beam_count: int,
        launcher_count: int,
    ) -> int:
        override = self.combo_log_overrides.get(combo_id)
        if override is not None:
            return override

        hull_weight = self._hull_marginal_log_weight(hull.id)

        hull_category = resolve_inference_hull_category(
            hull,
            beam_count=beam_count,
            launcher_count=launcher_count,
        )
        category_tables = self.component_tables[hull_category]
        fill = slot_fill_pattern(hull, beam_count=beam_count, launcher_count=launcher_count)

        component_weight = 0
        component_weight += category_tables["engines"].get(engine.id, 0)
        if beam is not None and beam_count > 0:
            component_weight += category_tables["beams"].get(beam.id, 0)
        if torpedo is not None and launcher_count > 0:
            component_weight += category_tables["torpedoes"].get(torpedo.id, 0)
        component_weight += category_tables.get("slotFill", {}).get(fill, 0)

        return hull_weight + component_weight

    def aggregate_probability_weight(self, action_id: str) -> int | None:
        return self.aggregate_action_weights.get(action_id)

    def probability_buckets_for_action(
        self,
        action_id: str,
        base_buckets: tuple[ProbabilityBucket, ...],
    ) -> tuple[ProbabilityBucket, ...]:
        marginal_weights = self.aggregate_bucket_marginal_weights.get(action_id)
        if marginal_weights is None:
            return base_buckets
        if len(marginal_weights) != len(base_buckets):
            raise ValueError(f"prior bucket count for {action_id} does not match solver buckets")
        return tuple(
            ProbabilityBucket(
                label=bucket.label,
                lower_count=bucket.lower_count,
                upper_count=bucket.upper_count,
                marginal_weight=weight,
            )
            for bucket, weight in zip(base_buckets, marginal_weights, strict=True)
        )


def _histogram_bucket_counts(
    histogram: dict[int, float],
    buckets: tuple[ProbabilityBucket, ...],
) -> dict[int, float]:
    bucket_counts = dict.fromkeys(range(len(buckets)), 0.0)
    for magnitude, count in histogram.items():
        bucket_counts[magnitude_bin_index(magnitude, buckets)] += count
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
    race_counts: dict[Any, float] = {}
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
    counts: dict[Any, float],
    *,
    universe: frozenset[int],
    field_name: str,
    scale: int,
) -> dict[Any, int]:
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
) -> dict[Any, int]:
    if not universe:
        return {}
    return counts_to_log_weights(implicit_uniform_component_counts(universe), scale=scale)


def _resolve_category_component_tables(
    tables: dict[str, dict[Any, float]] | None,
    *,
    band: ShipLimitBand,
    category: InferenceHullCategory,
    universe_by_table: dict[str, frozenset[int]],
    scale: int,
) -> dict[str, dict[Any, int]]:
    asset_tables = tables or {}
    resolved_tables: dict[str, dict[Any, int]] = {}
    for table_name, counts in asset_tables.items():
        if table_name == "slotFill":
            resolved_tables[table_name] = counts_to_log_weights(counts, scale=scale)
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
) -> dict[InferenceHullCategory, dict[str, dict[Any, int]]]:
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


def _resolve_aggregate_weights(
    asset: PriorWeightsAsset,
    *,
    band: ShipLimitBand,
    scale: int,
) -> tuple[dict[str, int], dict[str, tuple[int, ...]]]:
    action_weights: dict[str, int] = {}
    bucket_weights: dict[str, tuple[int, ...]] = {}
    band_tables = asset.aggregates.get(band, {})

    for action_id, aggregate in band_tables.items():
        if isinstance(aggregate, HistogramAggregate):
            if not is_histogram_aggregate_action(action_id):
                raise ValueError(
                    f"aggregates.{band}.{action_id!r} is not a known bucketed aggregate action"
                )
            base_buckets = base_buckets_for_action(action_id)
            if base_buckets is None:
                raise ValueError(
                    f"aggregates.{band}.{action_id!r} has no solver bucket definition"
                )
            bucket_counts = _histogram_bucket_counts(aggregate.histogram, base_buckets)
            log_weights = counts_to_log_weights(bucket_counts, scale=scale)
            bucket_weights[action_id] = tuple(
                log_weights[index] for index in range(len(base_buckets))
            )
        elif isinstance(aggregate, CountsAggregate):
            if not is_counts_aggregate_action(action_id):
                raise ValueError(
                    f"aggregates.{band}.{action_id!r} is not a known counts aggregate action"
                )
            (count_key, count_value), = aggregate.counts.items()
            action_weights[action_id] = counts_to_log_weights(
                {count_key: count_value},
                scale=scale,
            )[count_key]
    return action_weights, bucket_weights


def resolve_prior_weights_catalog(
    observation: InferenceObservation,
    settings: GameSettings,
    *,
    race_id: int | None = None,
    buildable_hull_ids: frozenset[int] = frozenset(),
    eligible_engine_ids: frozenset[int] = frozenset(),
    eligible_beam_ids: frozenset[int] = frozenset(),
    eligible_torp_ids: frozenset[int] = frozenset(),
    base_dir: Path | None = None,
    scale: int = INFERENCE_PROBABILITY_WEIGHT_SCALE,
) -> PriorWeightsCatalog:
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
    aggregate_action_weights, aggregate_bucket_weights = _resolve_aggregate_weights(
        asset,
        band=band,
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
        hull_log_weights=hull_log_weights,
        component_tables=component_tables,
        aggregate_action_weights=aggregate_action_weights,
        aggregate_bucket_marginal_weights=aggregate_bucket_weights,
        combo_log_overrides=combo_log_overrides,
        hull_log_overrides=hull_log_overrides_int,
    )

"""Resolve inference build prior catalogs from loaded assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api.analytics.military_score_inference.aggregate_action_registry import (
    SHIP_TORPS_LOADED_ACTION_PREFIX,
    base_bin_bounds_for_action,
    magnitude_bin_index,
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
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    ProbabilityBinBounds,
    ProbabilityBucket,
    probability_buckets_from_bin_bounds,
)
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
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import GameSettings

# Synthetic hull id in prior-weight asset hull tables (not a buildable in-game hull).
# Freighter combo likelihood uses this pseudo-hull's marginal log weight when no
# per-combo override is present; see prior_weights_standard.yaml hulls.999999.
GENERIC_FREIGHTER_PRIOR_HULL_ID = 999999

__all__ = [
    "GENERIC_FREIGHTER_PRIOR_HULL_ID",
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
    _hull_log_weights: dict[int, int]
    _component_tables: dict[
        InferenceHullCategory,
        dict[str, dict[Any, int]],
    ]
    _aggregate_action_weights: dict[str, int]
    _aggregate_bucket_marginal_weights: dict[str, tuple[int, ...]]
    _combo_log_overrides: dict[str, int]
    _hull_log_overrides: dict[int, int]

    @classmethod
    def from_resolved_tables(
        cls,
        *,
        diagnostics: PriorWeightsDiagnostics,
        hull_log_weights: dict[int, int],
        component_tables: dict[InferenceHullCategory, dict[str, dict[Any, int]]],
        aggregate_action_weights: dict[str, int],
        aggregate_bucket_marginal_weights: dict[str, tuple[int, ...]],
        combo_log_overrides: dict[str, int],
        hull_log_overrides: dict[int, int],
    ) -> PriorWeightsCatalog:
        return cls(
            diagnostics=diagnostics,
            _hull_log_weights=hull_log_weights,
            _component_tables=component_tables,
            _aggregate_action_weights=aggregate_action_weights,
            _aggregate_bucket_marginal_weights=aggregate_bucket_marginal_weights,
            _combo_log_overrides=combo_log_overrides,
            _hull_log_overrides=hull_log_overrides,
        )

    def hull_marginal_log_weight(self, hull_id: int, *, default_weight: int = 0) -> int:
        hull_override = self._hull_log_overrides.get(hull_id)
        if hull_override is not None:
            return hull_override
        return self._hull_log_weights.get(hull_id, default_weight)

    def component_log_weight(
        self,
        hull_category: InferenceHullCategory,
        table_name: str,
        key: Any,
        *,
        default_weight: int = 0,
    ) -> int:
        category_tables = self._component_tables[hull_category]
        return category_tables.get(table_name, {}).get(key, default_weight)

    def _resolved_combo_log_weight(
        self,
        *,
        combo_id: str,
        composed_weight: int,
    ) -> int:
        override = self._combo_log_overrides.get(combo_id)
        if override is not None:
            return override
        return composed_weight

    def freighter_probability_weight(self, *, combo_id: str, default_weight: int) -> int:
        """Freighter likelihood: combo override, else pseudo-hull marginal.

        See ``GENERIC_FREIGHTER_PRIOR_HULL_ID``.
        """
        return self._resolved_combo_log_weight(
            combo_id=combo_id,
            composed_weight=self.hull_marginal_log_weight(
                GENERIC_FREIGHTER_PRIOR_HULL_ID,
                default_weight=default_weight,
            ),
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
        hull_weight = self.hull_marginal_log_weight(hull.id)

        hull_category = resolve_inference_hull_category(
            hull,
            beam_count=beam_count,
            launcher_count=launcher_count,
        )
        category_tables = self._component_tables[hull_category]
        fill = slot_fill_pattern(hull, beam_count=beam_count, launcher_count=launcher_count)

        component_weight = 0
        component_weight += category_tables["engines"].get(engine.id, 0)
        if beam is not None and beam_count > 0:
            component_weight += category_tables["beams"].get(beam.id, 0)
        if torpedo is not None and launcher_count > 0:
            component_weight += category_tables["torpedoes"].get(torpedo.id, 0)
        component_weight += category_tables.get("slotFill", {}).get(fill, 0)

        return self._resolved_combo_log_weight(
            combo_id=combo_id,
            composed_weight=hull_weight + component_weight,
        )

    def aggregate_probability_weight(self, action_id: str) -> int | None:
        return self._aggregate_action_weights.get(action_id)

    def probability_buckets_for_action(
        self,
        action_id: str,
        bin_bounds: tuple[ProbabilityBinBounds, ...],
    ) -> tuple[ProbabilityBucket, ...]:
        marginal_weights = self._aggregate_bucket_marginal_weights.get(action_id)
        if marginal_weights is None:
            raise ValueError(
                f"incomplete prior: missing histogram marginal weights for aggregate action "
                f"{action_id!r}"
            )
        if len(marginal_weights) != len(bin_bounds):
            raise ValueError(f"prior bucket count for {action_id} does not match solver bins")
        return probability_buckets_from_bin_bounds(bin_bounds, marginal_weights)


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


def _implicit_uniform_histogram_bucket_weights(
    bin_bounds: tuple[ProbabilityBinBounds, ...],
    *,
    scale: int,
) -> tuple[int, ...]:
    bucket_counts = implicit_uniform_component_counts(frozenset(range(len(bin_bounds))))
    log_weights = counts_to_log_weights(bucket_counts, scale=scale)
    return tuple(log_weights[index] for index in range(len(bin_bounds)))


def _fill_implicit_uniform_torpedo_histograms(
    bucket_weights: dict[str, tuple[int, ...]],
    eligible_torp_ids: frozenset[int],
    *,
    scale: int,
) -> dict[str, tuple[int, ...]]:
    filled = dict(bucket_weights)
    for torp_id in eligible_torp_ids:
        action_id = f"{SHIP_TORPS_LOADED_ACTION_PREFIX}{torp_id}"
        if action_id in filled:
            continue
        bin_bounds = base_bin_bounds_for_action(action_id)
        if bin_bounds is None:
            raise ValueError(
                f"eligible torpedo {torp_id} has no solver bin definition for {action_id!r}"
            )
        filled[action_id] = _implicit_uniform_histogram_bucket_weights(bin_bounds, scale=scale)
    return filled


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
            bin_bounds = base_bin_bounds_for_action(action_id)
            if bin_bounds is None:
                raise ValueError(f"aggregates.{band}.{action_id!r} has no solver bin definition")
            bucket_counts = _histogram_bucket_counts(aggregate.histogram, bin_bounds)
            log_weights = counts_to_log_weights(bucket_counts, scale=scale)
            bucket_weights[action_id] = tuple(
                log_weights[index] for index in range(len(bin_bounds))
            )
        elif isinstance(aggregate, CountsAggregate):
            ((count_key, count_value),) = aggregate.counts.items()
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
    if eligible_torp_ids:
        aggregate_bucket_weights = _fill_implicit_uniform_torpedo_histograms(
            aggregate_bucket_weights,
            eligible_torp_ids,
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

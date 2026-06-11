"""Resolve inference build prior catalogs from loaded assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from api.analytics.military_score_inference.hull_category import (
    InferenceHullCategory,
    resolve_inference_hull_category,
    slot_fill_pattern,
)
from api.analytics.military_score_inference.inference_game_category import (
    resolve_inference_game_category,
)
from api.analytics.military_score_inference.models import InferenceObservation, ProbabilityBucket
from api.analytics.military_score_inference.prior_weights_asset import (
    COMPONENT_TABLE_NAMES,
    PriorWeightsAsset,
    ShipLimitBand,
    default_prior_weights_dir,
    load_prior_weights_for_category,
    parse_prior_weights_document,
    prior_weights_asset_path,
)
from api.analytics.military_score_inference.prior_weights_laplace import (
    PRIOR_WEIGHT_SCALE,
    WILDCARD_COUNT_KEY,
    counts_to_log_weights,
    expand_wildcard_counts,
    finalize_counts_for_laplace,
    implicit_uniform_component_counts,
    laplace_log_weight,
)
from api.analytics.military_score_inference.probability_bucket_defaults import (
    PLANET_DEFENSE_POST_BUCKETS,
    SHIP_FIGHTER_BUCKETS,
    SHIP_TORPEDO_BUCKETS,
    STARBASE_DEFENSE_POST_BUCKETS,
    STARBASE_FIGHTER_BUCKETS,
)
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import GameSettings

BUCKETED_AGGREGATE_ACTION_IDS = frozenset(
    {
        "planet_defense_posts_added_total",
        "starbase_defense_posts_added_total",
        "starbase_fighters_added_total",
        "ship_fighters_added_total",
    }
)

BASE_BUCKETS_BY_ACTION_ID: dict[str, tuple[ProbabilityBucket, ...]] = {
    "planet_defense_posts_added_total": PLANET_DEFENSE_POST_BUCKETS,
    "starbase_defense_posts_added_total": STARBASE_DEFENSE_POST_BUCKETS,
    "starbase_fighters_added_total": STARBASE_FIGHTER_BUCKETS,
    "ship_fighters_added_total": SHIP_FIGHTER_BUCKETS,
}

__all__ = [
    "BUCKETED_AGGREGATE_ACTION_IDS",
    "PRIOR_WEIGHT_SCALE",
    "WILDCARD_COUNT_KEY",
    "PriorWeightsCatalog",
    "PriorWeightsDiagnostics",
    "counts_to_log_weights",
    "default_prior_weights_dir",
    "expand_wildcard_counts",
    "implicit_uniform_component_counts",
    "laplace_log_weight",
    "load_prior_weights_for_category",
    "parse_prior_weights_document",
    "prior_weights_asset_path",
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
    eligible_engine_ids: frozenset[int] = frozenset()
    eligible_beam_ids: frozenset[int] = frozenset()
    eligible_torp_ids: frozenset[int] = frozenset()
    scale: int = PRIOR_WEIGHT_SCALE

    def _component_log_weights(
        self,
        hull_category: InferenceHullCategory,
        table_name: Literal["engines", "beams", "torpedoes"],
    ) -> dict[Any, int]:
        category_tables = self.component_tables.get(hull_category, {})
        if table_name in category_tables:
            return category_tables[table_name]
        universe_by_table = {
            "engines": self.eligible_engine_ids,
            "beams": self.eligible_beam_ids,
            "torpedoes": self.eligible_torp_ids,
        }
        universe = universe_by_table[table_name]
        if not universe:
            return {}
        return counts_to_log_weights(
            implicit_uniform_component_counts(universe),
            scale=self.scale,
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

        hull_override = self.hull_log_overrides.get(hull.id)
        hull_weight = (
            hull_override if hull_override is not None else self.hull_log_weights.get(hull.id, 0)
        )

        hull_category = resolve_inference_hull_category(
            hull,
            beam_count=beam_count,
            launcher_count=launcher_count,
        )
        category_tables = self.component_tables.get(hull_category, {})
        fill = slot_fill_pattern(hull, beam_count=beam_count, launcher_count=launcher_count)

        component_weight = 0
        component_weight += self._component_log_weights(hull_category, "engines").get(engine.id, 0)
        if beam is not None and beam_count > 0:
            component_weight += self._component_log_weights(hull_category, "beams").get(beam.id, 0)
        if torpedo is not None and launcher_count > 0:
            component_weight += self._component_log_weights(hull_category, "torpedoes").get(
                torpedo.id,
                0,
            )
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
        assigned = False
        for index, bucket in enumerate(buckets):
            lower_bound = 1 if bucket.lower_count == 0 else bucket.lower_count
            if lower_bound <= magnitude <= bucket.upper_count:
                bucket_counts[index] += count
                assigned = True
                break
        if not assigned:
            bucket_counts[len(buckets) - 1] += count
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
        field_name=f"hulls.{band}",
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
        field_name=field_name,
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
    resolved: dict[InferenceHullCategory, dict[str, dict[Any, int]]] = {}
    universe_by_table = {
        "engines": eligible_engine_ids,
        "beams": eligible_beam_ids,
        "torpedoes": eligible_torp_ids,
    }
    for category, tables in band_tables.items():
        resolved_tables: dict[str, dict[Any, int]] = {}
        for table_name, counts in tables.items():
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
        resolved[category] = resolved_tables
    return resolved


def _resolve_aggregate_weights(
    asset: PriorWeightsAsset,
    *,
    band: ShipLimitBand,
    scale: int,
) -> tuple[dict[str, int], dict[str, tuple[int, ...]]]:
    action_weights: dict[str, int] = {}
    bucket_weights: dict[str, tuple[int, ...]] = {}
    band_tables = asset.aggregates.get(band, {})

    for action_id, tables in band_tables.items():
        if "histogram" in tables:
            base_buckets = BASE_BUCKETS_BY_ACTION_ID.get(action_id)
            if base_buckets is None and action_id.startswith("ship_torps_loaded_"):
                base_buckets = SHIP_TORPEDO_BUCKETS
            if base_buckets is None:
                continue
            bucket_counts = _histogram_bucket_counts(tables["histogram"], base_buckets)
            log_weights = counts_to_log_weights(bucket_counts, scale=scale)
            bucket_weights[action_id] = tuple(
                log_weights[index] for index in range(len(base_buckets))
            )
        elif "counts" in tables:
            log_weights = counts_to_log_weights(tables["counts"], scale=scale)
            if log_weights:
                action_weights[action_id] = next(iter(log_weights.values()))
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
    scale: int = PRIOR_WEIGHT_SCALE,
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
        eligible_engine_ids=eligible_engine_ids,
        eligible_beam_ids=eligible_beam_ids,
        eligible_torp_ids=eligible_torp_ids,
        scale=scale,
    )

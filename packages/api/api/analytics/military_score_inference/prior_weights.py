"""Load inference build prior assets and resolve catalog probability weights."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from api.analytics.military_score_inference.hull_category import (
    InferenceHullCategory,
    resolve_inference_hull_category,
    slot_fill_pattern,
)
from api.analytics.military_score_inference.inference_game_category import (
    STANDARD_INFERENCE_GAME_CATEGORY,
    resolve_inference_game_category,
)
from api.analytics.military_score_inference.models import InferenceObservation, ProbabilityBucket
from api.analytics.military_score_inference.probability_bucket_defaults import (
    PLANET_DEFENSE_POST_BUCKETS,
    SHIP_FIGHTER_BUCKETS,
    SHIP_TORPEDO_BUCKETS,
    STARBASE_DEFENSE_POST_BUCKETS,
    STARBASE_FIGHTER_BUCKETS,
)
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import GameSettings

ShipLimitBand = Literal["before_ship_limit", "after_ship_limit"]

WILDCARD_COUNT_KEY = "*"

LAPLACE_ALPHA = 1
PRIOR_WEIGHT_SCALE = 100
IMPLICIT_UNIFORM_PSEUDO_COUNT = 1.0

COMPONENT_TABLE_NAMES = ("engines", "beams", "torpedoes")

STANDARD_PRIOR_FILENAME = f"prior_weights_{STANDARD_INFERENCE_GAME_CATEGORY}.yaml"

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


def default_prior_weights_dir() -> Path:
    return (
        Path(__file__).resolve().parents[5]
        / "assets"
        / "analytics"
        / "military_score_build_inference"
    )


def ship_limit_band_key(observation: InferenceObservation) -> ShipLimitBand:
    if observation.is_after_ship_limit:
        return "after_ship_limit"
    return "before_ship_limit"


def laplace_log_weight(count: float, *, total: float, cell_count: int, scale: int) -> int:
    probability = (count + LAPLACE_ALPHA) / (total + LAPLACE_ALPHA * cell_count)
    return round(scale * math.log(probability))


def counts_to_log_weights(
    counts: dict[Any, float],
    *,
    scale: int = PRIOR_WEIGHT_SCALE,
) -> dict[Any, int]:
    if not counts:
        return {}
    if WILDCARD_COUNT_KEY in counts:
        raise ValueError(f"wildcard {WILDCARD_COUNT_KEY!r} must be expanded before log conversion")
    total = float(sum(counts.values()))
    cell_count = len(counts)
    return {
        key: laplace_log_weight(value, total=total, cell_count=cell_count, scale=scale)
        for key, value in counts.items()
    }


def _finalize_counts_for_laplace(counts: dict[Any, float]) -> dict[Any, float]:
    if counts.keys() == {WILDCARD_COUNT_KEY}:
        return {"default": counts[WILDCARD_COUNT_KEY]}
    if WILDCARD_COUNT_KEY in counts:
        raise ValueError(f"unexpanded {WILDCARD_COUNT_KEY!r} remains in count table")
    return counts


def implicit_uniform_component_counts(universe: frozenset[int]) -> dict[int, float]:
    """Equal pseudo-count per eligible id when a component sub-table is absent from the asset."""
    return dict.fromkeys(universe, IMPLICIT_UNIFORM_PSEUDO_COUNT)


def expand_wildcard_counts(
    counts: dict[Any, float],
    *,
    universe: frozenset[Any] | None,
    field_name: str,
) -> dict[Any, float]:
    """Expand optional ``*`` default pseudo-count across ``universe`` before Laplace conversion."""
    if WILDCARD_COUNT_KEY not in counts:
        return dict(counts)

    wildcard_value = counts[WILDCARD_COUNT_KEY]
    explicit = {key: value for key, value in counts.items() if key != WILDCARD_COUNT_KEY}

    expanded = dict(explicit)
    for item_id in universe:
        if item_id not in expanded:
            expanded[item_id] = wildcard_value
    if not expanded and wildcard_value is not None:
        return {WILDCARD_COUNT_KEY: wildcard_value}
    return expanded


def _parse_count_table(
    raw: object,
    *,
    field_name: str,
    key_kind: Literal["int", "str"],
    allow_wildcard: bool,
) -> dict[Any, float]:
    if not isinstance(raw, dict):
        raise ValueError(f"{field_name} must be a mapping")
    counts: dict[Any, float] = {}
    for key, value in raw.items():
        if allow_wildcard and key == WILDCARD_COUNT_KEY:
            parsed_key: Any = WILDCARD_COUNT_KEY
        elif key_kind == "int":
            if not isinstance(key, int):
                raise ValueError(f"{field_name} keys must be integers")
            parsed_key = key
        else:
            if not isinstance(key, str):
                raise ValueError(f"{field_name} keys must be strings")
            if not allow_wildcard and key == WILDCARD_COUNT_KEY:
                raise ValueError(f"{field_name} does not allow {WILDCARD_COUNT_KEY!r}")
            parsed_key = key
        if not allow_wildcard and key == WILDCARD_COUNT_KEY:
            raise ValueError(f"{field_name} does not allow {WILDCARD_COUNT_KEY!r}")
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"{field_name} values must be non-negative numbers")
        if parsed_key in counts:
            raise ValueError(f"{field_name} contains duplicate key {parsed_key!r}")
        counts[parsed_key] = float(value)
    return counts


def _parse_int_keyed_counts(
    raw: object,
    *,
    field_name: str,
    allow_wildcard: bool = True,
) -> dict[Any, float]:
    return _parse_count_table(
        raw,
        field_name=field_name,
        key_kind="int",
        allow_wildcard=allow_wildcard,
    )


def _parse_str_keyed_counts(
    raw: object,
    *,
    field_name: str,
    allow_wildcard: bool = True,
) -> dict[str, float]:
    parsed = _parse_count_table(
        raw,
        field_name=field_name,
        key_kind="str",
        allow_wildcard=allow_wildcard,
    )
    return parsed


@dataclass(frozen=True)
class PriorWeightsAsset:
    version: int
    category: str
    game_category_rules_version: int
    hulls: dict[ShipLimitBand, dict[str, dict[int, float]]]
    components: dict[ShipLimitBand, dict[InferenceHullCategory, dict[str, dict[Any, float]]]]
    aggregates: dict[ShipLimitBand, dict[str, dict[str, dict[int, float]]]]
    combo_overrides: dict[str, float] = field(default_factory=dict)
    hull_overrides: dict[int, float] = field(default_factory=dict)


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


def _parse_hull_tables(raw: object) -> dict[ShipLimitBand, dict[str, dict[int, float]]]:
    if not isinstance(raw, dict):
        raise ValueError("hulls must be a mapping")
    parsed: dict[ShipLimitBand, dict[str, dict[int, float]]] = {}
    for band in ("before_ship_limit", "after_ship_limit"):
        band_raw = raw.get(band)
        if not isinstance(band_raw, dict):
            raise ValueError(f"hulls.{band} must be a mapping")
        global_counts = _parse_int_keyed_counts(
            band_raw.get("global", {}),
            field_name=f"hulls.{band}.global",
        )
        by_race: dict[str, dict[int, float]] = {"global": global_counts}
        race_raw = band_raw.get("byRace", {})
        if race_raw is not None:
            if not isinstance(race_raw, dict):
                raise ValueError(f"hulls.{band}.byRace must be a mapping")
            for race_id, race_counts in race_raw.items():
                if not isinstance(race_id, int):
                    raise ValueError(f"hulls.{band}.byRace keys must be integers")
                by_race[str(race_id)] = _parse_int_keyed_counts(
                    race_counts,
                    field_name=f"hulls.{band}.byRace[{race_id}]",
                )
        parsed[band] = by_race
    return parsed


def _parse_component_tables(
    raw: object,
) -> dict[ShipLimitBand, dict[InferenceHullCategory, dict[str, dict[Any, float]]]]:
    if not isinstance(raw, dict):
        raise ValueError("components must be a mapping")
    parsed: dict[ShipLimitBand, dict[InferenceHullCategory, dict[str, dict[Any, float]]]] = {}
    for band in ("before_ship_limit", "after_ship_limit"):
        band_raw = raw.get(band)
        if not isinstance(band_raw, dict):
            raise ValueError(f"components.{band} must be a mapping")
        categories: dict[InferenceHullCategory, dict[str, dict[Any, float]]] = {}
        for category, category_raw in band_raw.items():
            if not isinstance(category, str):
                raise ValueError(f"components.{band} keys must be strings")
            if not isinstance(category_raw, dict):
                raise ValueError(f"components.{band}.{category} must be a mapping")
            tables: dict[str, dict[Any, float]] = {}
            for table_name in ("engines", "beams", "torpedoes"):
                if table_name in category_raw:
                    tables[table_name] = _parse_int_keyed_counts(
                        category_raw[table_name],
                        field_name=f"components.{band}.{category}.{table_name}",
                    )
            if "slotFill" in category_raw:
                tables["slotFill"] = _parse_str_keyed_counts(
                    category_raw["slotFill"],
                    field_name=f"components.{band}.{category}.slotFill",
                    allow_wildcard=False,
                )
            categories[category] = tables
        parsed[band] = categories
    return parsed


def _parse_aggregate_tables(
    raw: object,
) -> dict[ShipLimitBand, dict[str, dict[str, dict[int, float]]]]:
    if not isinstance(raw, dict):
        raise ValueError("aggregates must be a mapping")
    parsed: dict[ShipLimitBand, dict[str, dict[str, dict[int, float]]]] = {}
    for band in ("before_ship_limit", "after_ship_limit"):
        band_raw = raw.get(band)
        if not isinstance(band_raw, dict):
            raise ValueError(f"aggregates.{band} must be a mapping")
        actions: dict[str, dict[str, dict[int, float]]] = {}
        for action_id, action_raw in band_raw.items():
            if not isinstance(action_id, str):
                raise ValueError(f"aggregates.{band} keys must be strings")
            if not isinstance(action_raw, dict):
                raise ValueError(f"aggregates.{band}.{action_id} must be a mapping")
            if "histogram" in action_raw:
                actions[action_id] = {
                    "histogram": _parse_int_keyed_counts(
                        action_raw["histogram"],
                        field_name=f"aggregates.{band}.{action_id}.histogram",
                        allow_wildcard=False,
                    )
                }
            elif "counts" in action_raw:
                actions[action_id] = {
                    "counts": _parse_str_keyed_counts(
                        action_raw["counts"],
                        field_name=f"aggregates.{band}.{action_id}.counts",
                    )
                }
            else:
                raise ValueError(f"aggregates.{band}.{action_id} must include histogram or counts")
        parsed[band] = actions
    return parsed


def parse_prior_weights_document(document: dict[str, Any]) -> PriorWeightsAsset:
    version = document.get("version")
    if not isinstance(version, int) or version < 1:
        raise ValueError("prior weights version must be a positive integer")

    category = document.get("category")
    if not isinstance(category, str) or not category:
        raise ValueError("prior weights category must be a non-empty string")

    rules_version = document.get("gameCategoryRulesVersion")
    if not isinstance(rules_version, int) or rules_version < 1:
        raise ValueError("gameCategoryRulesVersion must be a positive integer")

    overrides_raw = document.get("overrides", {})
    combo_overrides: dict[str, float] = {}
    hull_overrides: dict[int, float] = {}
    if overrides_raw is not None:
        if not isinstance(overrides_raw, dict):
            raise ValueError("overrides must be a mapping")
        combo_raw = overrides_raw.get("combos", {})
        if combo_raw:
            combo_overrides = _parse_str_keyed_counts(
                combo_raw,
                field_name="overrides.combos",
                allow_wildcard=False,
            )
        hull_raw = overrides_raw.get("hulls", {})
        if hull_raw:
            hull_overrides = _parse_int_keyed_counts(
                hull_raw,
                field_name="overrides.hulls",
                allow_wildcard=False,
            )

    return PriorWeightsAsset(
        version=version,
        category=category,
        game_category_rules_version=rules_version,
        hulls=_parse_hull_tables(document.get("hulls")),
        components=_parse_component_tables(document.get("components")),
        aggregates=_parse_aggregate_tables(document.get("aggregates")),
        combo_overrides=combo_overrides,
        hull_overrides=hull_overrides,
    )


def load_prior_weights_asset(path: Path) -> PriorWeightsAsset:
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"prior weights root must be a mapping: {path}")
    asset = parse_prior_weights_document(document)
    expected_stem = f"prior_weights_{asset.category}"
    if path.stem != expected_stem:
        raise ValueError(
            f"prior weights category {asset.category!r} does not match filename stem {path.stem!r}"
        )
    return asset


def prior_weights_asset_path(
    category_id: str,
    *,
    base_dir: Path | None = None,
) -> Path:
    directory = default_prior_weights_dir() if base_dir is None else base_dir
    return directory / f"prior_weights_{category_id}.yaml"


def load_prior_weights_for_category(
    category_id: str,
    *,
    base_dir: Path | None = None,
) -> tuple[PriorWeightsAsset, Path, bool]:
    directory = default_prior_weights_dir() if base_dir is None else base_dir
    category_path = directory / f"prior_weights_{category_id}.yaml"
    if category_path.is_file():
        return load_prior_weights_asset(category_path), category_path, False

    if category_id == STANDARD_INFERENCE_GAME_CATEGORY:
        raise FileNotFoundError(f"missing required prior weights asset: {category_path}")

    standard_path = directory / STANDARD_PRIOR_FILENAME
    if not standard_path.is_file():
        raise FileNotFoundError(f"missing required prior weights asset: {standard_path}")
    return load_prior_weights_asset(standard_path), standard_path, True


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
    return counts_to_log_weights(_finalize_counts_for_laplace(expanded), scale=scale)


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
    return counts_to_log_weights(_finalize_counts_for_laplace(expanded), scale=scale)


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

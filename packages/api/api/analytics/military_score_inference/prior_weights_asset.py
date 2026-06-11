"""YAML parsing and loading for inference build prior weight assets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeAlias, overload

import yaml

from api.analytics.military_score_inference.aggregate_action_registry import (
    AggregateActionSpec,
    iter_aggregate_action_slots,
    lookup_aggregate_action_spec,
)
from api.analytics.military_score_inference.hull_category import (
    INFERENCE_HULL_CATEGORIES,
    InferenceHullCategory,
)
from api.analytics.military_score_inference.inference_game_category import (
    INFERENCE_GAME_CATEGORY_RULES_VERSION,
    STANDARD_INFERENCE_GAME_CATEGORY,
)
from api.analytics.military_score_inference.prior_weights_laplace import WILDCARD_COUNT_KEY
from api.analytics.scores_assets import Scores

ShipLimitBand = Literal["before_ship_limit", "after_ship_limit"]

SHIP_LIMIT_BANDS: tuple[ShipLimitBand, ...] = ("before_ship_limit", "after_ship_limit")

COMPONENT_TABLE_NAMES = ("engines", "beams", "torpedoes")

WildcardCountKey = Literal["*"]
IntComponentTableName = Literal["engines", "beams", "torpedoes"]
SlotFillTableName = Literal["slotFill"]

IntCountTable: TypeAlias = dict[int, float]
IntCountTableInput: TypeAlias = dict[int | WildcardCountKey, float]
SlotFillCountTable: TypeAlias = dict[str, float]
ComponentCountTables: TypeAlias = dict[str, IntCountTableInput | SlotFillCountTable]

STANDARD_PRIOR_FILENAME = f"prior_weights_{STANDARD_INFERENCE_GAME_CATEGORY}.yaml"


def default_prior_weights_dir() -> Path:
    return Scores.assets_dir()


def _parse_ship_limit_bands[T](
    raw: object,
    *,
    section_name: str,
    parse_band: Callable[[object, ShipLimitBand], T],
) -> dict[ShipLimitBand, T]:
    if not isinstance(raw, dict):
        raise ValueError(f"{section_name} must be a mapping")
    parsed: dict[ShipLimitBand, T] = {}
    for band in SHIP_LIMIT_BANDS:
        band_raw = raw.get(band)
        if not isinstance(band_raw, dict):
            raise ValueError(f"{section_name}.{band} must be a mapping")
        parsed[band] = parse_band(band_raw, band)
    return parsed


def _parse_count_table(
    raw: object,
    *,
    field_name: str,
    key_kind: Literal["int", "str"],
    allow_wildcard: bool,
) -> IntCountTableInput | SlotFillCountTable:
    if not isinstance(raw, dict):
        raise ValueError(f"{field_name} must be a mapping")
    if key_kind == "int":
        counts: IntCountTableInput = {}
    else:
        counts = {}
    for key, value in raw.items():
        if allow_wildcard and key == WILDCARD_COUNT_KEY:
            if key_kind != "int":
                raise ValueError(f"{field_name} does not allow {WILDCARD_COUNT_KEY!r}")
            parsed_key: int | WildcardCountKey = WILDCARD_COUNT_KEY
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
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"{field_name} values must be non-negative numbers")
        if parsed_key in counts:
            raise ValueError(f"{field_name} contains duplicate key {parsed_key!r}")
        counts[parsed_key] = float(value)
    return counts


@overload
def _parse_int_keyed_counts(
    raw: object,
    *,
    field_name: str,
    allow_wildcard: Literal[True] = True,
) -> IntCountTableInput: ...


@overload
def _parse_int_keyed_counts(
    raw: object,
    *,
    field_name: str,
    allow_wildcard: Literal[False],
) -> IntCountTable: ...


def _parse_int_keyed_counts(
    raw: object,
    *,
    field_name: str,
    allow_wildcard: bool = True,
) -> IntCountTableInput | IntCountTable:
    parsed = _parse_count_table(
        raw,
        field_name=field_name,
        key_kind="int",
        allow_wildcard=allow_wildcard,
    )
    return parsed


def _parse_str_keyed_counts(
    raw: object,
    *,
    field_name: str,
    allow_wildcard: bool = True,
) -> SlotFillCountTable:
    return _parse_count_table(
        raw,
        field_name=field_name,
        key_kind="str",
        allow_wildcard=allow_wildcard,
    )


@dataclass(frozen=True)
class HistogramAggregate:
    histogram: dict[int, float]


@dataclass(frozen=True)
class CountsAggregate:
    pseudo_count: float


AggregatePrior = HistogramAggregate | CountsAggregate


@dataclass(frozen=True)
class PriorWeightsAsset:
    version: int
    category: str
    game_category_rules_version: int
    hulls: dict[ShipLimitBand, dict[str, dict[int, float]]]
    components: dict[ShipLimitBand, dict[InferenceHullCategory, ComponentCountTables]]
    aggregates: dict[ShipLimitBand, dict[str, AggregatePrior]]
    combo_overrides: dict[str, float] = field(default_factory=dict)
    hull_overrides: dict[int, float] = field(default_factory=dict)


def _parse_band_hull_tables(
    band_raw: object,
    band: ShipLimitBand,
) -> dict[str, dict[int, float]]:
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
    return by_race


def _parse_hull_tables(raw: object) -> dict[ShipLimitBand, dict[str, dict[int, float]]]:
    return _parse_ship_limit_bands(
        raw,
        section_name="hulls",
        parse_band=_parse_band_hull_tables,
    )


def _parse_band_component_tables(
    band_raw: object,
    band: ShipLimitBand,
) -> dict[InferenceHullCategory, ComponentCountTables]:
    categories: dict[InferenceHullCategory, ComponentCountTables] = {}
    for category, category_raw in band_raw.items():
        if not isinstance(category, str):
            raise ValueError(f"components.{band} keys must be strings")
        if category not in INFERENCE_HULL_CATEGORIES:
            allowed = ", ".join(INFERENCE_HULL_CATEGORIES)
            raise ValueError(
                f"components.{band}.{category!r} is not a valid inference hull category; "
                f"expected one of: {allowed}"
            )
        if not isinstance(category_raw, dict):
            raise ValueError(f"components.{band}.{category} must be a mapping")
        tables: ComponentCountTables = {}
        for table_name in COMPONENT_TABLE_NAMES:
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
    return categories


def _parse_component_tables(
    raw: object,
) -> dict[ShipLimitBand, dict[InferenceHullCategory, ComponentCountTables]]:
    return _parse_ship_limit_bands(
        raw,
        section_name="components",
        parse_band=_parse_band_component_tables,
    )


def _parse_band_aggregate_tables(
    band_raw: object,
    band: ShipLimitBand,
) -> dict[str, AggregatePrior]:
    actions: dict[str, AggregatePrior] = {}
    for action_id, action_raw in band_raw.items():
        if not isinstance(action_id, str):
            raise ValueError(f"aggregates.{band} keys must be strings")
        if not isinstance(action_raw, dict):
            raise ValueError(f"aggregates.{band}.{action_id} must be a mapping")
        if "histogram" in action_raw:
            spec = lookup_aggregate_action_spec(action_id)
            if spec is None or spec.prior_shape != "histogram":
                raise ValueError(
                    f"aggregates.{band}.{action_id!r} is not a known bucketed aggregate action"
                )
            actions[action_id] = HistogramAggregate(
                histogram=_parse_int_keyed_counts(
                    action_raw["histogram"],
                    field_name=f"aggregates.{band}.{action_id}.histogram",
                    allow_wildcard=False,
                )
            )
        elif "counts" in action_raw:
            spec = lookup_aggregate_action_spec(action_id)
            if spec is None or spec.prior_shape != "counts":
                raise ValueError(
                    f"aggregates.{band}.{action_id!r} is not a known counts aggregate action"
                )
            counts_raw = action_raw["counts"]
            if not isinstance(counts_raw, dict):
                raise ValueError(f"aggregates.{band}.{action_id}.counts must be a mapping")
            if len(counts_raw) != 1:
                raise ValueError(f"aggregates.{band}.{action_id}.counts must have exactly one key")
            ((count_key, count_value),) = counts_raw.items()
            if not isinstance(count_key, str):
                raise ValueError(f"aggregates.{band}.{action_id}.counts keys must be strings")
            if not isinstance(count_value, (int, float)):
                raise ValueError(f"aggregates.{band}.{action_id}.counts values must be numbers")
            actions[action_id] = CountsAggregate(pseudo_count=float(count_value))
        else:
            raise ValueError(f"aggregates.{band}.{action_id} must include histogram or counts")
    return actions


def _parse_aggregate_tables(
    raw: object,
) -> dict[ShipLimitBand, dict[str, AggregatePrior]]:
    return _parse_ship_limit_bands(
        raw,
        section_name="aggregates",
        parse_band=_parse_band_aggregate_tables,
    )


def lookup_slot_aggregate_prior(
    band_tables: dict[str, AggregatePrior],
    *,
    band: ShipLimitBand,
    action_id: str,
    spec: AggregateActionSpec,
) -> HistogramAggregate | CountsAggregate | None:
    """Look up and validate the aggregate prior for a catalog slot.

    Returns None when the slot allows implicit uniform and no aggregate is present.
    Raises ValueError with an ``incomplete prior:`` prefix when a required slot is
    missing or present with the wrong shape.
    """
    aggregate = band_tables.get(action_id)
    if aggregate is None:
        if spec.missing_aggregate_policy == "required":
            raise ValueError(
                f"incomplete prior: aggregates.{band} missing required action {action_id!r}"
            )
        return None
    if spec.prior_shape == "histogram":
        if not isinstance(aggregate, HistogramAggregate):
            raise ValueError(
                f"incomplete prior: aggregates.{band}.{action_id!r} must be a histogram"
            )
        return aggregate
    if spec.prior_shape == "counts":
        if not isinstance(aggregate, CountsAggregate):
            raise ValueError(
                f"incomplete prior: aggregates.{band}.{action_id!r} must be counts"
            )
        return aggregate
    raise ValueError(
        f"incomplete prior: aggregates.{band}.{action_id!r} has unsupported shape"
    )


def validate_complete_aggregate_priors(asset: PriorWeightsAsset, *, band: ShipLimitBand) -> None:
    band_tables = asset.aggregates.get(band, {})
    for slot in iter_aggregate_action_slots(eligible_torp_ids=frozenset()):
        if slot.spec.missing_aggregate_policy != "required":
            continue
        lookup_slot_aggregate_prior(
            band_tables,
            band=band,
            action_id=slot.action_id,
            spec=slot.spec,
        )


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
    if rules_version != INFERENCE_GAME_CATEGORY_RULES_VERSION:
        raise ValueError(
            "gameCategoryRulesVersion "
            f"{rules_version} does not match expected inference rules version "
            f"{INFERENCE_GAME_CATEGORY_RULES_VERSION}"
        )

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

    asset = PriorWeightsAsset(
        version=version,
        category=category,
        game_category_rules_version=rules_version,
        hulls=_parse_hull_tables(document.get("hulls")),
        components=_parse_component_tables(document.get("components")),
        aggregates=_parse_aggregate_tables(document.get("aggregates")),
        combo_overrides=combo_overrides,
        hull_overrides=hull_overrides,
    )
    for band in SHIP_LIMIT_BANDS:
        validate_complete_aggregate_priors(asset, band=band)
    return asset


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

"""YAML parsing and loading for inference build prior weight assets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeAlias, overload

import yaml

from api.analytics.military_score_inference.aggregate_action_registry import (
    AggregateActionSpec,
    is_pooled_torp_load_prior_key,
    iter_aggregate_action_slots,
    lookup_aggregate_action_spec,
)
from api.analytics.military_score_inference.hull_category import (
    INFERENCE_HULL_CATEGORIES,
    InferenceHullCategory,
)
from api.analytics.military_score_inference.prior_weights_laplace import WILDCARD_COUNT_KEY
from api.analytics.scores_assets import Scores
from api.concepts.game_category import GAME_CATEGORY_RULES_VERSION, GameCategory

ShipLimitBand = Literal["before_ship_limit", "after_ship_limit"]

SHIP_LIMIT_BANDS: tuple[ShipLimitBand, ...] = ("before_ship_limit", "after_ship_limit")

COMPONENT_TABLE_NAMES = ("engines", "beams", "torpedoes")

CategoryHullCountTables: TypeAlias = dict[InferenceHullCategory, dict[int, float]]
RaceHullTables: TypeAlias = dict[str, CategoryHullCountTables]

WildcardCountKey = Literal["*"]
IntComponentTableName = Literal["engines", "beams", "torpedoes"]
SlotFillTableName = Literal["slotFill"]

IntCountTable: TypeAlias = dict[int, float]
IntCountTableInput: TypeAlias = dict[int | WildcardCountKey, float]
SlotFillCountTable: TypeAlias = dict[str, float]


@dataclass
class ComponentCountTables:
    engines: IntCountTableInput | None = None
    beams: IntCountTableInput | None = None
    torpedoes: IntCountTableInput | None = None
    slot_fill: SlotFillCountTable | None = None


STANDARD_PRIOR_FILENAME = f"prior_weights_{GameCategory.STANDARD}.yaml"


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


def _parse_histogram_counts(raw: object, *, field_name: str) -> IntCountTable:
    histogram = _parse_int_keyed_counts(
        raw,
        field_name=field_name,
        allow_wildcard=False,
    )
    for magnitude in histogram:
        if magnitude < 0:
            raise ValueError(f"{field_name} keys must be non-negative integers")
    return histogram


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
class PriorWeightsAsset:
    version: int
    category: str
    game_category_rules_version: int
    hulls: dict[ShipLimitBand, RaceHullTables]
    components: dict[ShipLimitBand, dict[InferenceHullCategory, ComponentCountTables]]
    aggregates: dict[ShipLimitBand, dict[str, HistogramAggregate]]
    combo_overrides: dict[str, float] = field(default_factory=dict)
    hull_overrides: dict[int, float] = field(default_factory=dict)
    contributing_game_ids: tuple[int, ...] = ()


def _is_legacy_flat_hull_counts(global_raw: dict[object, object]) -> bool:
    """True when ``global`` maps hull ids to counts (asset version < 4)."""
    for _key, value in global_raw.items():
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, dict):
            return False
    return False


def _parse_category_hull_tables(
    raw: object,
    *,
    field_name: str,
) -> CategoryHullCountTables:
    if not isinstance(raw, dict):
        raise ValueError(f"{field_name} must be a mapping")
    parsed: CategoryHullCountTables = {}
    for category_key, category_raw in raw.items():
        if not isinstance(category_key, str):
            raise ValueError(f"{field_name} keys must be strings")
        if category_key not in INFERENCE_HULL_CATEGORIES:
            allowed = ", ".join(INFERENCE_HULL_CATEGORIES)
            raise ValueError(
                f"{field_name}.{category_key!r} is not a valid inference hull category; "
                f"expected one of: {allowed}"
            )
        parsed[category_key] = _parse_int_keyed_counts(
            category_raw,
            field_name=f"{field_name}.{category_key}",
        )
    return parsed


def _parse_band_hull_tables(
    band_raw: object,
    band: ShipLimitBand,
) -> RaceHullTables:
    if not isinstance(band_raw, dict):
        raise ValueError(f"hulls.{band} must be a mapping")
    global_raw = band_raw.get("global", {})
    if not isinstance(global_raw, dict):
        raise ValueError(f"hulls.{band}.global must be a mapping")
    if _is_legacy_flat_hull_counts(global_raw):
        raise ValueError(
            f"hulls.{band}.global uses legacy unconditional hull counts; "
            "migrate assets to version 4 category-keyed hull tables "
            "(scripts/migrate_prior_hull_tables_to_category.py)"
        )
    by_race: RaceHullTables = {
        "global": _parse_category_hull_tables(global_raw, field_name=f"hulls.{band}.global"),
    }
    race_raw = band_raw.get("byRace", {})
    if race_raw is not None:
        if not isinstance(race_raw, dict):
            raise ValueError(f"hulls.{band}.byRace must be a mapping")
        for race_id, race_counts in race_raw.items():
            if not isinstance(race_id, int):
                raise ValueError(f"hulls.{band}.byRace keys must be integers")
            by_race[str(race_id)] = _parse_category_hull_tables(
                race_counts,
                field_name=f"hulls.{band}.byRace[{race_id}]",
            )
    return by_race


def _parse_hull_tables(raw: object) -> dict[ShipLimitBand, RaceHullTables]:
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
        engines = None
        beams = None
        torpedoes = None
        for table_name in COMPONENT_TABLE_NAMES:
            if table_name in category_raw:
                parsed = _parse_int_keyed_counts(
                    category_raw[table_name],
                    field_name=f"components.{band}.{category}.{table_name}",
                )
                if table_name == "engines":
                    engines = parsed
                elif table_name == "beams":
                    beams = parsed
                else:
                    torpedoes = parsed
        slot_fill = None
        if "slotFill" in category_raw:
            slot_fill = _parse_str_keyed_counts(
                category_raw["slotFill"],
                field_name=f"components.{band}.{category}.slotFill",
                allow_wildcard=False,
            )
        categories[category] = ComponentCountTables(
            engines=engines,
            beams=beams,
            torpedoes=torpedoes,
            slot_fill=slot_fill,
        )
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
) -> dict[str, HistogramAggregate]:
    actions: dict[str, HistogramAggregate] = {}
    for action_id, action_raw in band_raw.items():
        if not isinstance(action_id, str):
            raise ValueError(f"aggregates.{band} keys must be strings")
        if not isinstance(action_raw, dict):
            raise ValueError(f"aggregates.{band}.{action_id} must be a mapping")
        if "histogram" not in action_raw:
            raise ValueError(f"aggregates.{band}.{action_id} must include a histogram")
        if (
            not is_pooled_torp_load_prior_key(action_id)
            and lookup_aggregate_action_spec(action_id) is None
        ):
            raise ValueError(f"aggregates.{band}.{action_id!r} is not a known aggregate action")
        # Histogram keys are non-negative magnitude counts; an optional 0 key carries
        # the occurrence (count == 0) pseudo-count routed into the leading none bin.
        actions[action_id] = HistogramAggregate(
            histogram=_parse_histogram_counts(
                action_raw["histogram"],
                field_name=f"aggregates.{band}.{action_id}.histogram",
            )
        )
    return actions


def _parse_aggregate_tables(
    raw: object,
) -> dict[ShipLimitBand, dict[str, HistogramAggregate]]:
    return _parse_ship_limit_bands(
        raw,
        section_name="aggregates",
        parse_band=_parse_band_aggregate_tables,
    )


def lookup_slot_aggregate_prior(
    band_tables: dict[str, HistogramAggregate],
    *,
    band: ShipLimitBand,
    action_id: str,
    spec: AggregateActionSpec,
) -> HistogramAggregate | None:
    """Look up and validate the aggregate histogram prior for a catalog slot.

    Returns None when the slot allows implicit uniform and no aggregate is present.
    Raises ValueError with an ``incomplete prior:`` prefix when a required slot is
    missing.
    """
    aggregate = band_tables.get(action_id)
    if aggregate is None:
        if spec.missing_aggregate_policy == "required":
            raise ValueError(
                f"incomplete prior: aggregates.{band} missing required action {action_id!r}"
            )
        return None
    return aggregate


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


def parse_prior_weights_document(
    document: dict[str, Any],
    *,
    require_complete_aggregates: bool = True,
) -> PriorWeightsAsset:
    version = document.get("version")
    if not isinstance(version, int) or version < 4:
        raise ValueError("prior weights version must be an integer >= 4")

    category = document.get("category")
    if not isinstance(category, str) or not category:
        raise ValueError("prior weights category must be a non-empty string")

    rules_version = document.get("gameCategoryRulesVersion")
    if not isinstance(rules_version, int) or rules_version < 1:
        raise ValueError("gameCategoryRulesVersion must be a positive integer")
    if rules_version != GAME_CATEGORY_RULES_VERSION:
        raise ValueError(
            "gameCategoryRulesVersion "
            f"{rules_version} does not match expected game category rules version "
            f"{GAME_CATEGORY_RULES_VERSION}"
        )

    overrides_raw = document.get("overrides", {})
    combo_overrides: dict[str, float] = {}
    hull_overrides: dict[int, float] = {}
    contributing_game_ids: tuple[int, ...] = ()
    contributing_raw = document.get("contributingGameIds")
    if contributing_raw is not None:
        if not isinstance(contributing_raw, list):
            raise ValueError("contributingGameIds must be a list")
        parsed_ids: list[int] = []
        for game_id in contributing_raw:
            if not isinstance(game_id, int):
                raise ValueError("contributingGameIds entries must be integers")
            if game_id in parsed_ids:
                raise ValueError(f"contributingGameIds contains duplicate id {game_id}")
            parsed_ids.append(game_id)
        contributing_game_ids = tuple(parsed_ids)
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
        contributing_game_ids=contributing_game_ids,
    )
    for band in SHIP_LIMIT_BANDS:
        if require_complete_aggregates:
            validate_complete_aggregate_priors(asset, band=band)
    return asset


def load_prior_weights_asset(
    path: Path,
    *,
    require_complete_aggregates: bool = True,
) -> PriorWeightsAsset:
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"prior weights root must be a mapping: {path}")
    asset = parse_prior_weights_document(
        document,
        require_complete_aggregates=require_complete_aggregates,
    )
    expected_stem = f"prior_weights_{asset.category}"
    if path.stem != expected_stem:
        raise ValueError(
            f"prior weights category {asset.category!r} does not match filename stem {path.stem!r}"
        )
    return asset


def create_empty_prior_weights_asset(category: GameCategory) -> PriorWeightsAsset:
    """Return a merge-ready prior asset with no counts (for first-time category mining)."""
    return PriorWeightsAsset(
        version=4,
        category=category.value,
        game_category_rules_version=GAME_CATEGORY_RULES_VERSION,
        hulls={band: {"global": {}} for band in SHIP_LIMIT_BANDS},
        components={band: {} for band in SHIP_LIMIT_BANDS},
        aggregates={band: {} for band in SHIP_LIMIT_BANDS},
    )


def load_prior_weights_for_category(
    category: GameCategory,
    *,
    base_dir: Path | None = None,
) -> tuple[PriorWeightsAsset, Path, bool]:
    directory = default_prior_weights_dir() if base_dir is None else base_dir
    category_path = directory / f"prior_weights_{category}.yaml"
    if category_path.is_file():
        return load_prior_weights_asset(category_path), category_path, False

    if category == GameCategory.STANDARD:
        raise FileNotFoundError(f"missing required prior weights asset: {category_path}")

    standard_path = directory / STANDARD_PRIOR_FILENAME
    if not standard_path.is_file():
        raise FileNotFoundError(f"missing required prior weights asset: {standard_path}")
    return load_prior_weights_asset(standard_path), standard_path, True

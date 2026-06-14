"""Merge mined counts into inference prior weight assets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from api.analytics.military_score_inference.prior_weights_asset import (
    SHIP_LIMIT_BANDS,
    ComponentCountTables,
    PriorWeightsAsset,
    ShipLimitBand,
    create_empty_prior_weights_asset,
    load_prior_weights_asset,
    parse_prior_weights_document,
)
from api.concepts.game_category import GAME_CATEGORY_RULES_VERSION, GameCategory

from .accumulation import PriorMiningAccumulation
from .asset_write import write_commented_prior_weights_asset
from .component_name_catalog import ComponentNameCatalog


def prior_weights_path_for_category(category: GameCategory, *, base_dir: Path) -> Path:
    return base_dir / f"prior_weights_{category.value}.yaml"


def load_or_empty_asset(category: GameCategory, *, base_dir: Path) -> PriorWeightsAsset | None:
    path = prior_weights_path_for_category(category, base_dir=base_dir)
    if not path.is_file():
        return None
    return load_prior_weights_asset(path, require_complete_aggregates=False)


def load_or_bootstrap_asset(category: GameCategory, *, base_dir: Path) -> PriorWeightsAsset:
    """Load an existing asset or return an empty merge target for a new category file."""
    existing = load_or_empty_asset(category, base_dir=base_dir)
    if existing is not None:
        return existing
    return create_empty_prior_weights_asset(category)


def is_prior_weights_asset_present(category: GameCategory, *, base_dir: Path) -> bool:
    return prior_weights_path_for_category(category, base_dir=base_dir).is_file()


def merge_accumulation_into_asset(
    asset: PriorWeightsAsset,
    accumulation: PriorMiningAccumulation,
    *,
    provenance_game_ids: tuple[int, ...],
) -> PriorWeightsAsset:
    merged_hulls = _merge_hull_tables(asset.hulls, accumulation.hull_counts)
    merged_components = _merge_component_tables(asset.components, accumulation.component_counts)
    merged_aggregates = _merge_aggregate_tables(asset.aggregates, accumulation.aggregate_histograms)
    merged_game_ids = _merge_contributing_game_ids(asset.contributing_game_ids, provenance_game_ids)
    return PriorWeightsAsset(
        version=asset.version,
        category=asset.category,
        game_category_rules_version=GAME_CATEGORY_RULES_VERSION,
        hulls=merged_hulls,
        components=merged_components,
        aggregates=merged_aggregates,
        combo_overrides=dict(asset.combo_overrides),
        hull_overrides=dict(asset.hull_overrides),
        contributing_game_ids=merged_game_ids,
    )


def write_prior_weights_asset(
    path: Path,
    asset: PriorWeightsAsset,
    *,
    name_catalog: ComponentNameCatalog,
) -> None:
    write_commented_prior_weights_asset(path, asset, name_catalog=name_catalog)


def asset_to_document(asset: PriorWeightsAsset) -> dict[str, Any]:
    document: dict[str, Any] = {
        "version": asset.version,
        "category": asset.category,
        "gameCategoryRulesVersion": asset.game_category_rules_version,
        "hulls": _serialize_hull_tables(asset.hulls),
        "components": _serialize_component_tables(asset.components),
        "aggregates": _serialize_aggregate_tables(asset.aggregates),
    }
    if asset.contributing_game_ids:
        document["contributingGameIds"] = list(asset.contributing_game_ids)
    if asset.combo_overrides or asset.hull_overrides:
        overrides: dict[str, Any] = {}
        if asset.combo_overrides:
            overrides["combos"] = dict(asset.combo_overrides)
        if asset.hull_overrides:
            overrides["hulls"] = dict(asset.hull_overrides)
        document["overrides"] = overrides
    return document


def _merge_contributing_game_ids(
    existing: tuple[int, ...],
    new_ids: tuple[int, ...],
) -> tuple[int, ...]:
    merged: list[int] = list(existing)
    seen = set(existing)
    for game_id in new_ids:
        if game_id in seen:
            continue
        merged.append(game_id)
        seen.add(game_id)
    return tuple(merged)


def _merge_hull_tables(
    asset_tables: dict,
    mined_tables: dict,
) -> dict:
    merged = _deep_copy_hull_tables(asset_tables)
    for band in SHIP_LIMIT_BANDS:
        for race_key, hull_table in mined_tables.get(band, {}).items():
            target = merged[band].setdefault(race_key, {})
            for hull_id, count in hull_table.items():
                target[hull_id] = target.get(hull_id, 0.0) + count
    return merged


def _merge_component_tables(asset_tables: dict, mined_tables: dict) -> dict:
    merged = _deep_copy_component_tables(asset_tables)
    for band in SHIP_LIMIT_BANDS:
        for category, tables in mined_tables.get(band, {}).items():
            existing = merged[band].get(category)
            if existing is None:
                merged[band][category] = ComponentCountTables(
                    engines=dict(tables.get("engines", {})) or None,
                    beams=dict(tables.get("beams", {})) or None,
                    torpedoes=dict(tables.get("torpedoes", {})) or None,
                    slot_fill=dict(tables.get("slotFill", {})) or None,
                )
                continue
            for table_name, attr_name in (
                ("engines", "engines"),
                ("beams", "beams"),
                ("torpedoes", "torpedoes"),
                ("slotFill", "slot_fill"),
            ):
                mined_counts = tables.get(table_name)
                if not mined_counts:
                    continue
                current = getattr(existing, attr_name) or {}
                merged_counts = dict(current)
                for key, count in mined_counts.items():
                    merged_counts[key] = merged_counts.get(key, 0.0) + count
                setattr(existing, attr_name, merged_counts)
    return merged


def _merge_aggregate_tables(asset_tables: dict, mined_tables: dict) -> dict:
    from api.analytics.military_score_inference.prior_weights_asset import HistogramAggregate

    merged: dict = {band: dict(asset_tables[band]) for band in SHIP_LIMIT_BANDS}
    for band in SHIP_LIMIT_BANDS:
        for action_id, histogram in mined_tables.get(band, {}).items():
            existing = merged[band].get(action_id)
            if existing is None:
                merged_counts = dict(histogram)
            else:
                merged_counts = dict(existing.histogram)
                for magnitude, count in histogram.items():
                    merged_counts[magnitude] = merged_counts.get(magnitude, 0.0) + count
            merged[band][action_id] = HistogramAggregate(histogram=merged_counts)
    return merged


def _deep_copy_hull_tables(tables: dict) -> dict:
    return {
        band: {race_key: dict(hull_table) for race_key, hull_table in band_tables.items()}
        for band, band_tables in tables.items()
    }


def _deep_copy_component_tables(tables: dict) -> dict:
    copied: dict = {}
    for band, categories in tables.items():
        copied[band] = {}
        for category, component_tables in categories.items():
            copied[band][category] = ComponentCountTables(
                engines=dict(component_tables.engines) if component_tables.engines else None,
                beams=dict(component_tables.beams) if component_tables.beams else None,
                torpedoes=dict(component_tables.torpedoes) if component_tables.torpedoes else None,
                slot_fill=dict(component_tables.slot_fill) if component_tables.slot_fill else None,
            )
    return copied


def _serialize_hull_tables(tables: dict) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for band in SHIP_LIMIT_BANDS:
        band_tables = tables[band]
        global_counts = dict(band_tables.get("global", {}))
        by_race: dict[int, dict[int, float]] = {}
        for race_key, hull_table in band_tables.items():
            if race_key == "global":
                continue
            by_race[int(race_key)] = dict(hull_table)
        band_payload: dict[str, Any] = {"global": global_counts}
        if by_race:
            band_payload["byRace"] = by_race
        serialized[band] = band_payload
    return serialized


def _serialize_component_tables(tables: dict) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for band in SHIP_LIMIT_BANDS:
        band_payload: dict[str, Any] = {}
        for category, component_tables in tables[band].items():
            category_payload: dict[str, Any] = {}
            for table_name, yaml_key in (
                ("engines", "engines"),
                ("beams", "beams"),
                ("torpedoes", "torpedoes"),
                ("slot_fill", "slotFill"),
            ):
                counts = getattr(component_tables, table_name)
                if counts:
                    category_payload[yaml_key] = dict(counts)
            if category_payload:
                band_payload[category] = category_payload
        serialized[band] = band_payload
    return serialized


def _serialize_aggregate_tables(tables: dict) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for band in SHIP_LIMIT_BANDS:
        band_payload: dict[str, Any] = {}
        for action_id, aggregate in sorted(tables[band].items()):
            band_payload[action_id] = {"histogram": dict(aggregate.histogram)}
        serialized[band] = band_payload
    return serialized


def parse_asset_document_for_merge(document: dict[str, Any]) -> PriorWeightsAsset:
    return parse_prior_weights_document(document)


def accumulation_mining_report_sections(accumulation: PriorMiningAccumulation) -> dict[str, Any]:
    """Shape mined counts for the JSON miner report (matches asset histogram layout)."""
    total_ship_builds = 0.0
    for band_tables in accumulation.hull_counts.values():
        total_ship_builds += sum(band_tables.get("global", {}).values())
    return {
        "total_ship_builds": int(total_ship_builds),
        "hulls": _serialize_hull_tables(accumulation.hull_counts),
        "components": _serialize_accumulation_component_tables(accumulation.component_counts),
        "aggregate_histograms": _serialize_accumulation_aggregate_histograms(
            accumulation.aggregate_histograms
        ),
    }


def _serialize_accumulation_component_tables(tables: dict) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    table_keys = (
        ("engines", "engines"),
        ("beams", "beams"),
        ("torpedoes", "torpedoes"),
        ("slotFill", "slotFill"),
    )
    for band in SHIP_LIMIT_BANDS:
        band_payload: dict[str, Any] = {}
        for category, component_tables in tables.get(band, {}).items():
            if not isinstance(component_tables, dict):
                continue
            category_payload: dict[str, Any] = {}
            for source_key, yaml_key in table_keys:
                counts = component_tables.get(source_key)
                if counts:
                    category_payload[yaml_key] = dict(counts)
            if category_payload:
                band_payload[category] = category_payload
        serialized[band] = band_payload
    return serialized


def _serialize_accumulation_aggregate_histograms(
    tables: dict[ShipLimitBand, dict[str, dict[int, float]]],
) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for band in SHIP_LIMIT_BANDS:
        band_payload: dict[str, Any] = {}
        for action_id, histogram in sorted(tables.get(band, {}).items()):
            band_payload[action_id] = {
                "histogram": {
                    str(magnitude): count for magnitude, count in sorted(histogram.items())
                }
            }
        serialized[band] = band_payload
    return serialized

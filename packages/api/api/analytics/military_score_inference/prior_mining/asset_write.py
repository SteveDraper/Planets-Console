"""Write inference prior weight assets with template header and id annotations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from api.analytics.military_score_inference.aggregate_action_registry import (
    SHIP_TORPS_LOADED_ACTION_PREFIX,
)
from api.analytics.military_score_inference.hull_category import INFERENCE_HULL_CATEGORIES
from api.analytics.military_score_inference.prior_weights_asset import (
    SHIP_LIMIT_BANDS,
    PriorWeightsAsset,
)
from api.analytics.military_score_inference.prior_weights_laplace import WILDCARD_COUNT_KEY
from api.analytics.scores_assets import Scores

from .component_name_catalog import ComponentNameCatalog

HULL_CATEGORY_COMMENTS: dict[str, str] = {
    "beam_ship": "resolve_inference_hull_category() label",
    "carrier": "",
    "torpedo_ship": "",
    "battleship": "",
    "true_freighter": "",
    "alchemy_ship": "",
    "weaponless_hull": "",
    "utility": "",
}

SLOT_FILL_COMMENTS: dict[str, str] = {
    "full": "all hull weapon slots filled",
    "partial": "",
}


def default_prior_weights_template_path() -> Path:
    return Scores.assets_dir() / "prior_weights_asset.template.yaml"


def template_header_lines(*, category: str, template_path: Path | None = None) -> list[str]:
    path = default_prior_weights_template_path() if template_path is None else template_path
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("version:"):
            break
        if line.startswith("# This file is the comment and outline template"):
            continue
        lines.append(line.replace("__CATEGORY__", category))
    return lines


def render_commented_prior_weights_yaml(
    asset: PriorWeightsAsset,
    *,
    name_catalog: ComponentNameCatalog,
    template_path: Path | None = None,
) -> str:
    catalog = name_catalog
    lines: list[str] = []
    lines.extend(template_header_lines(category=asset.category, template_path=template_path))
    lines.append(f"version: {asset.version}")
    lines.append(
        f"category: {asset.category}  # must match filename stem prior_weights_{{category}}.yaml"
    )
    lines.append(
        "gameCategoryRulesVersion: "
        f"{asset.game_category_rules_version}  "
        "# bump when GameCategory.from_game_settings() rules change"
    )
    lines.append("")
    lines.extend(_render_hulls(asset, catalog))
    lines.append("")
    lines.extend(_render_components(asset, catalog))
    lines.append("")
    lines.extend(_render_aggregates(asset, catalog))
    if asset.combo_overrides or asset.hull_overrides or _should_emit_empty_overrides(asset):
        lines.append("")
        lines.extend(_render_overrides(asset, catalog))
    if asset.contributing_game_ids:
        lines.append("")
        lines.append("contributingGameIds:")
        for game_id in asset.contributing_game_ids:
            lines.append(f"  - {game_id}")
    lines.append("")
    return "\n".join(lines)


def write_commented_prior_weights_asset(
    path: Path,
    asset: PriorWeightsAsset,
    *,
    name_catalog: ComponentNameCatalog,
    template_path: Path | None = None,
) -> None:
    content = render_commented_prior_weights_yaml(
        asset,
        name_catalog=name_catalog,
        template_path=template_path,
    )
    path.write_text(content, encoding="utf-8")


def _should_emit_empty_overrides(asset: PriorWeightsAsset) -> bool:
    return not asset.combo_overrides and not asset.hull_overrides


def _render_hulls(asset: PriorWeightsAsset, catalog: ComponentNameCatalog) -> list[str]:
    lines = [
        "hulls:",
        (
            "  # Inference ship-limit band: tables split on whether the player is "
            "before/after ship limit."
        ),
    ]
    for band in SHIP_LIMIT_BANDS:
        lines.append(f"  {band}:")
        band_tables = asset.hulls[band]
        global_counts = band_tables.get("global", {})
        if global_counts:
            lines.append("    global:")
            lines.extend(
                _render_int_count_table(global_counts, indent=6, catalog=catalog, table_kind="hull")
            )
        else:
            lines.append("    global: {}")
        by_race = {
            race_key: hull_table
            for race_key, hull_table in band_tables.items()
            if race_key != "global" and hull_table
        }
        if by_race:
            lines.append("    byRace:")
            for race_id in sorted(by_race, key=lambda key: int(key)):
                race_comment = catalog.race_name(int(race_id))
                race_suffix = f"  # {race_comment}" if race_comment else ""
                lines.append(f"      {race_id}:{race_suffix}")
                lines.extend(
                    _render_int_count_table(
                        by_race[race_id],
                        indent=8,
                        catalog=catalog,
                        table_kind="hull",
                    )
                )
    return lines


def _render_components(asset: PriorWeightsAsset, catalog: ComponentNameCatalog) -> list[str]:
    lines = [
        "components:",
        "  # Component conditional priors keyed by inference hull category (race-agnostic in v1).",
    ]
    for band in SHIP_LIMIT_BANDS:
        lines.append(f"  {band}:")
        band_categories = asset.components[band]
        if not band_categories:
            lines.append("    {}")
            continue
        for category in INFERENCE_HULL_CATEGORIES:
            component_tables = band_categories.get(category)
            if component_tables is None:
                continue
            category_comment = HULL_CATEGORY_COMMENTS.get(category, "")
            category_suffix = f"  # {category_comment}" if category_comment else ""
            lines.append(f"    {category}:{category_suffix}")
            for table_name, attr_name, table_kind in (
                ("engines", "engines", "engine"),
                ("beams", "beams", "beam"),
                ("torpedoes", "torpedoes", "torpedo"),
            ):
                counts = getattr(component_tables, attr_name)
                if not counts:
                    continue
                lines.append(f"      {table_name}:")
                lines.extend(
                    _render_int_count_table(
                        counts,
                        indent=8,
                        catalog=catalog,
                        table_kind=table_kind,
                    )
                )
            slot_fill = component_tables.slot_fill
            if slot_fill:
                lines.append("      slotFill:")
                lines.extend(_render_slot_fill_table(slot_fill, indent=8))
    return lines


def _render_aggregates(asset: PriorWeightsAsset, catalog: ComponentNameCatalog) -> list[str]:
    lines = ["aggregates:"]
    for band in SHIP_LIMIT_BANDS:
        lines.append(f"  {band}:")
        band_tables = asset.aggregates[band]
        if not band_tables:
            lines.append("    {}")
            continue
        for action_id in sorted(band_tables):
            aggregate = band_tables[action_id]
            histogram = aggregate.histogram
            if not histogram:
                continue
            lines.append(f"    {action_id}:")
            lines.append("      histogram:")
            lines.extend(_render_histogram(histogram, action_id=action_id, catalog=catalog))
    return lines


def _render_overrides(asset: PriorWeightsAsset, catalog: ComponentNameCatalog) -> list[str]:
    del catalog
    lines = ["overrides:"]
    if asset.combo_overrides:
        lines.append("  combos:")
        for combo_id, count in sorted(asset.combo_overrides.items()):
            lines.append(f"    {combo_id}: {count}")
    else:
        lines.append(
            "  combos: {}  # combo_id -> pseudo-count (optional sparse corrections; no wildcard)"
        )
    if asset.hull_overrides:
        lines.append("  hulls:")
        for hull_id, count in sorted(asset.hull_overrides.items()):
            lines.append(f"    {hull_id}: {count}")
    else:
        lines.append("  hulls: {}")
    return lines


def _render_int_count_table(
    counts: dict[Any, float],
    *,
    indent: int,
    catalog: ComponentNameCatalog,
    table_kind: str,
) -> list[str]:
    prefix = " " * indent
    lines: list[str] = []
    wildcard = counts.get(WILDCARD_COUNT_KEY)
    int_keys = sorted(key for key in counts if key != WILDCARD_COUNT_KEY)
    if wildcard is not None:
        if table_kind == "hull":
            comment = "default pseudo-count for any other buildable hull id"
        else:
            comment = ""
        suffix = f"  # {comment}" if comment else ""
        lines.append(f"{prefix}'*': {_format_count(wildcard)}{suffix}")
    for key in int_keys:
        if not isinstance(key, int):
            continue
        name = _lookup_component_name(catalog, table_kind, key)
        suffix = f"  # {name}" if name else ""
        lines.append(f"{prefix}{key}: {_format_count(counts[key])}{suffix}")
    return lines


def _render_slot_fill_table(counts: dict[str, float], *, indent: int) -> list[str]:
    prefix = " " * indent
    lines: list[str] = []
    for key in sorted(counts):
        comment = SLOT_FILL_COMMENTS.get(key, "")
        suffix = f"  # {comment}" if comment else ""
        lines.append(f"{prefix}{key}: {_format_count(counts[key])}{suffix}")
    return lines


def _render_histogram(
    histogram: dict[int, float],
    *,
    action_id: str,
    catalog: ComponentNameCatalog,
) -> list[str]:
    if len(histogram) <= 2 and action_id.startswith("fighters_"):
        compact = ", ".join(
            f"{magnitude}: {_format_count(count)}" for magnitude, count in sorted(histogram.items())
        )
        suffix = "  # occurrence-only: none bin + single active band"
        return [f"        {{{compact}}}{suffix}"]

    lines: list[str] = []
    first_positive = next((magnitude for magnitude in sorted(histogram) if magnitude > 0), None)
    torpedo_suffix = _torpedo_load_comment(action_id, catalog)
    for magnitude in sorted(histogram):
        count = histogram[magnitude]
        if magnitude == 0:
            suffix = "  # none-bin occurrence pseudo-count (count == 0)"
        elif magnitude == first_positive:
            if torpedo_suffix:
                suffix = f"  # {torpedo_suffix}"
            else:
                suffix = (
                    "  # magnitude (discrete total) -> pseudo-count; "
                    "rolled into solver buckets at load"
                )
        else:
            suffix = ""
        lines.append(f"        {magnitude}: {_format_count(count)}{suffix}")
    return lines


def _torpedo_load_comment(action_id: str, catalog: ComponentNameCatalog) -> str | None:
    if not action_id.startswith(SHIP_TORPS_LOADED_ACTION_PREFIX):
        return None
    torpedo_id_text = action_id.removeprefix(SHIP_TORPS_LOADED_ACTION_PREFIX)
    if not torpedo_id_text.isdigit():
        return None
    torpedo_id = int(torpedo_id_text)
    name = catalog.torpedo_name(torpedo_id)
    if name is None:
        return "load magnitudes"
    return f"{name} load magnitudes"


def _lookup_component_name(
    catalog: ComponentNameCatalog,
    table_kind: str,
    component_id: int,
) -> str | None:
    if table_kind == "hull":
        return catalog.hull_name(component_id)
    if table_kind == "engine":
        return catalog.engine_name(component_id)
    if table_kind == "beam":
        return catalog.beam_name(component_id)
    if table_kind == "torpedo":
        return catalog.torpedo_name(component_id)
    return None


def _format_count(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)

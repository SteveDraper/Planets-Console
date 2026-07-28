"""Homeworld layout distribution asset: center-distance and neighbor-separation.

Committed JSON under ``assets/analytics/homeworld-locator/``. Homeworld region
overlay paint uses ``supportMin``/``supportMax`` of center-distance as the
annular band. Layout-prior cost uses fitted Normal ``mean``/``std`` via
``-log`` density for both families (schema v2).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping

from api.analytics.homeworld_locator_assets import HomeworldLocator
from api.concepts.game_category import GameCategory

LAYOUT_DISTRIBUTIONS_FILENAME = "layout_distributions.json"
SCHEMA_VERSION = 2
DEFAULT_BIN_WIDTH_LY = 10
COST_MODEL_NORMAL_NEG_LOG_DENSITY = "normal_neg_log_density"

LayoutCategoryKey = Literal["epic", "standard"]

LAYOUT_CATEGORY_KEYS: tuple[LayoutCategoryKey, ...] = ("epic", "standard")


@dataclass(frozen=True)
class SmoothedMetricDistribution:
    """One metric table for a game category (empirical support + Normal fit)."""

    sample_count: int
    support_min: float
    support_max: float
    mean: float
    std: float

    def neg_log_density(self, value: float) -> float:
        """``-log φ(value; mean, std²)`` for layout-prior cost terms."""
        sigma = self.std if self.std > 1e-12 else 1e-12
        z = (value - self.mean) / sigma
        return 0.5 * math.log(2.0 * math.pi * sigma * sigma) + 0.5 * z * z


@dataclass(frozen=True)
class CategoryLayoutDistributions:
    center_distance: SmoothedMetricDistribution
    neighbor_separation: SmoothedMetricDistribution


@dataclass(frozen=True)
class LayoutDistributionsAsset:
    """Committed layout distribution tables for epic and standard circular maps."""

    schema_version: int
    bin_width_ly: float
    cost_model: str
    categories: dict[LayoutCategoryKey, CategoryLayoutDistributions]
    source: Mapping[str, Any]

    def for_category(self, category: GameCategory | str) -> CategoryLayoutDistributions:
        key: str = category.value if isinstance(category, GameCategory) else category
        if key not in LAYOUT_CATEGORY_KEYS:
            raise KeyError(f"layout distributions asset has no category {key!r}")
        return self.categories[key]

    def center_distance_band(self, category: GameCategory | str) -> tuple[float, float]:
        """Paint band radii: empirical center-distance support extremes."""
        metric = self.for_category(category).center_distance
        return metric.support_min, metric.support_max


def default_layout_distributions_path() -> Path:
    return HomeworldLocator.assets_dir() / LAYOUT_DISTRIBUTIONS_FILENAME


def distill_metric_from_histogram(
    counts: list[int],
    *,
    bin_width: float = DEFAULT_BIN_WIDTH_LY,
    sample_count: int | None = None,
) -> SmoothedMetricDistribution:
    """Trim empty bins for support; fit Normal mean/std from raw histogram mass.

    Leading/trailing zero bins are trimmed so ``supportMin``/``supportMax`` match
    observed support (paint / cull). Mean and std use unsmoothed bin midpoints
    over that trimmed range (population MLE).
    """
    if bin_width <= 0:
        raise ValueError("bin_width must be positive")
    if not counts:
        raise ValueError("histogram counts must be non-empty")
    if any(count < 0 for count in counts):
        raise ValueError("histogram counts must be non-negative")

    first = next((index for index, count in enumerate(counts) if count > 0), None)
    last = next(
        (index for index, count in reversed(list(enumerate(counts))) if count > 0),
        None,
    )
    if first is None or last is None:
        raise ValueError("histogram has no positive counts")

    trimmed = counts[first : last + 1]
    total = sum(trimmed)
    if total <= 0:
        raise ValueError("histogram mass must be positive")

    support_min = first * bin_width
    support_max = (last + 1) * bin_width

    weighted_sum = 0.0
    for offset, count in enumerate(trimmed):
        if count == 0:
            continue
        mid = (first + offset + 0.5) * bin_width
        weighted_sum += count * mid
    mean = weighted_sum / total

    var_acc = 0.0
    for offset, count in enumerate(trimmed):
        if count == 0:
            continue
        mid = (first + offset + 0.5) * bin_width
        delta = mid - mean
        var_acc += count * delta * delta
    std = math.sqrt(var_acc / total)
    if std <= 0.0:
        # Degenerate single-bin histogram: use half-bin as a floor.
        std = 0.5 * bin_width

    resolved_sample_count = sample_count if sample_count is not None else total
    return SmoothedMetricDistribution(
        sample_count=int(resolved_sample_count),
        support_min=round(support_min, 1),
        support_max=round(support_max, 1),
        mean=round(mean, 3),
        std=round(std, 3),
    )


def distill_layout_distributions_from_report(
    report: Mapping[str, Any],
    *,
    source: Mapping[str, Any] | None = None,
) -> LayoutDistributionsAsset:
    """Build the committed asset from a ``visualize_homeworld_distributions`` report."""
    bin_width = float(
        report.get("center_bin_width_ly")
        or report.get("neighbor_bin_width_ly")
        or DEFAULT_BIN_WIDTH_LY
    )
    center_section = report["center"]
    neighbor_section = report["neighbor"]
    categories: dict[LayoutCategoryKey, CategoryLayoutDistributions] = {}
    for category in LAYOUT_CATEGORY_KEYS:
        center_counts = [int(value) for value in center_section[category]]
        neighbor_counts = [int(value) for value in neighbor_section[category]]
        center_summary = center_section.get("summary", {}).get(category, {})
        neighbor_summary = neighbor_section.get("summary", {}).get(category, {})
        categories[category] = CategoryLayoutDistributions(
            center_distance=distill_metric_from_histogram(
                center_counts,
                bin_width=bin_width,
                sample_count=int(center_summary["n"]) if "n" in center_summary else None,
            ),
            neighbor_separation=distill_metric_from_histogram(
                neighbor_counts,
                bin_width=bin_width,
                sample_count=(int(neighbor_summary["n"]) if "n" in neighbor_summary else None),
            ),
        )

    resolved_source: dict[str, Any] = {
        "reportSource": report.get("source"),
        "storageRoot": report.get("storage_root"),
    }
    if source:
        resolved_source.update(dict(source))

    return LayoutDistributionsAsset(
        schema_version=SCHEMA_VERSION,
        bin_width_ly=bin_width,
        cost_model=COST_MODEL_NORMAL_NEG_LOG_DENSITY,
        categories=categories,
        source=resolved_source,
    )


def layout_distributions_asset_to_json(asset: LayoutDistributionsAsset) -> dict[str, Any]:
    """Serialize the asset to the committed JSON shape (camelCase keys)."""
    categories: dict[str, Any] = {}
    for key, category in asset.categories.items():
        categories[key] = {
            "centerDistance": _metric_to_json(category.center_distance),
            "neighborSeparation": _metric_to_json(category.neighbor_separation),
        }
    return {
        "schemaVersion": asset.schema_version,
        "binWidthLy": asset.bin_width_ly,
        "costModel": asset.cost_model,
        "source": dict(asset.source),
        "categories": categories,
    }


def layout_distributions_asset_from_json(raw: Mapping[str, Any]) -> LayoutDistributionsAsset:
    """Deserialize and validate a layout distributions asset payload."""
    if not isinstance(raw, Mapping):
        raise ValueError("layout distributions asset must be a JSON object")
    schema_version = raw.get("schemaVersion")
    if schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported layout distributions schemaVersion {schema_version!r}; "
            f"expected {SCHEMA_VERSION}"
        )
    bin_width = float(raw["binWidthLy"])
    cost_model = raw.get("costModel")
    if cost_model != COST_MODEL_NORMAL_NEG_LOG_DENSITY:
        raise ValueError(f"unsupported costModel {cost_model!r}")
    categories_raw = raw.get("categories")
    if not isinstance(categories_raw, Mapping):
        raise ValueError("categories must be an object")

    categories: dict[LayoutCategoryKey, CategoryLayoutDistributions] = {}
    for key in LAYOUT_CATEGORY_KEYS:
        category_raw = categories_raw.get(key)
        if not isinstance(category_raw, Mapping):
            raise ValueError(f"categories.{key} must be an object")
        categories[key] = CategoryLayoutDistributions(
            center_distance=_metric_from_json(
                category_raw.get("centerDistance"),
                field_name=f"categories.{key}.centerDistance",
            ),
            neighbor_separation=_metric_from_json(
                category_raw.get("neighborSeparation"),
                field_name=f"categories.{key}.neighborSeparation",
            ),
        )

    source = raw.get("source", {})
    if source is not None and not isinstance(source, Mapping):
        raise ValueError("source must be an object when present")

    return LayoutDistributionsAsset(
        schema_version=SCHEMA_VERSION,
        bin_width_ly=bin_width,
        cost_model=COST_MODEL_NORMAL_NEG_LOG_DENSITY,
        categories=categories,
        source=dict(source or {}),
    )


def load_layout_distributions_asset(
    path: Path | None = None,
) -> LayoutDistributionsAsset:
    """Load the committed layout distributions asset from disk."""
    asset_path = default_layout_distributions_path() if path is None else path
    raw = json.loads(asset_path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{asset_path} did not contain a JSON object")
    return layout_distributions_asset_from_json(raw)


@lru_cache(maxsize=1)
def load_default_layout_distributions_asset() -> LayoutDistributionsAsset:
    """Cached load of the shipped asset (process-lifetime)."""
    return load_layout_distributions_asset()


def write_layout_distributions_asset(
    asset: LayoutDistributionsAsset,
    path: Path | None = None,
) -> Path:
    """Write the asset JSON (pretty-printed, trailing newline)."""
    asset_path = default_layout_distributions_path() if path is None else path
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(layout_distributions_asset_to_json(asset), indent=2)
    asset_path.write_text(payload if payload.endswith("\n") else payload + "\n")
    load_default_layout_distributions_asset.cache_clear()
    return asset_path


def _metric_to_json(metric: SmoothedMetricDistribution) -> dict[str, Any]:
    return {
        "sampleCount": metric.sample_count,
        "supportMin": metric.support_min,
        "supportMax": metric.support_max,
        "mean": metric.mean,
        "std": metric.std,
    }


def _metric_from_json(raw: object, *, field_name: str) -> SmoothedMetricDistribution:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{field_name} must be an object")
    support_min = float(raw["supportMin"])
    support_max = float(raw["supportMax"])
    if support_max < support_min:
        raise ValueError(f"{field_name}: supportMax must be >= supportMin")
    mean = float(raw["mean"])
    std = float(raw["std"])
    if std <= 0.0:
        raise ValueError(f"{field_name}.std must be positive")
    return SmoothedMetricDistribution(
        sample_count=int(raw["sampleCount"]),
        support_min=support_min,
        support_max=support_max,
        mean=mean,
        std=std,
    )

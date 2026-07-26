"""Homeworld layout distribution asset: smoothed center-distance and neighbor-separation.

Committed JSON under ``assets/analytics/homeworld-locator/``. Homeworld region
overlay paint uses ``supportMin``/``supportMax`` of center-distance as the
annular band; percentile tables (center + neighbor) are for later likelihood
scoring.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping

from api.analytics.homeworld_locator_assets import HomeworldLocator
from api.concepts.game_category import GameCategory

LAYOUT_DISTRIBUTIONS_FILENAME = "layout_distributions.json"
SCHEMA_VERSION = 1
DEFAULT_BIN_WIDTH_LY = 10
DEFAULT_LAPLACE_ALPHA = 1.0
DEFAULT_PERCENTILE_STEP = 1
SMOOTHING_METHOD_LAPLACE = "laplace"

LayoutCategoryKey = Literal["epic", "standard"]

LAYOUT_CATEGORY_KEYS: tuple[LayoutCategoryKey, ...] = ("epic", "standard")


@dataclass(frozen=True)
class SmoothedMetricDistribution:
    """One smoothed metric table for a game category."""

    sample_count: int
    support_min: float
    support_max: float
    percentiles: tuple[float, ...]
    percentile_step: int = DEFAULT_PERCENTILE_STEP

    def value_at_percentile(self, percentile: float) -> float:
        """Interpolate the stored percentile grid (0..100)."""
        if not self.percentiles:
            raise ValueError("percentiles table is empty")
        if percentile <= 0:
            return self.percentiles[0]
        if percentile >= 100:
            return self.percentiles[-1]
        scaled = percentile / self.percentile_step
        lower_index = int(scaled)
        upper_index = min(lower_index + 1, len(self.percentiles) - 1)
        if lower_index == upper_index:
            return self.percentiles[lower_index]
        fraction = scaled - lower_index
        lower = self.percentiles[lower_index]
        upper = self.percentiles[upper_index]
        return lower + fraction * (upper - lower)


@dataclass(frozen=True)
class CategoryLayoutDistributions:
    center_distance: SmoothedMetricDistribution
    neighbor_separation: SmoothedMetricDistribution


@dataclass(frozen=True)
class LayoutDistributionsAsset:
    """Committed layout distribution tables for epic and standard circular maps."""

    schema_version: int
    bin_width_ly: float
    smoothing_method: str
    laplace_alpha: float
    percentile_step: int
    categories: dict[LayoutCategoryKey, CategoryLayoutDistributions]
    source: Mapping[str, Any]

    def for_category(self, category: GameCategory | str) -> CategoryLayoutDistributions:
        key: str = category.value if isinstance(category, GameCategory) else category
        if key not in LAYOUT_CATEGORY_KEYS:
            raise KeyError(f"layout distributions asset has no category {key!r}")
        return self.categories[key]

    def center_distance_band(self, category: GameCategory | str) -> tuple[float, float]:
        """Paint band radii: smoothed center-distance support extremes."""
        metric = self.for_category(category).center_distance
        return metric.support_min, metric.support_max


def default_layout_distributions_path() -> Path:
    return HomeworldLocator.assets_dir() / LAYOUT_DISTRIBUTIONS_FILENAME


def distill_metric_from_histogram(
    counts: list[int],
    *,
    bin_width: float = DEFAULT_BIN_WIDTH_LY,
    alpha: float = DEFAULT_LAPLACE_ALPHA,
    percentile_step: int = DEFAULT_PERCENTILE_STEP,
    sample_count: int | None = None,
) -> SmoothedMetricDistribution:
    """Laplace-smooth a histogram, invert the CDF onto a percentile grid.

    Leading/trailing zero bins are trimmed so Laplace mass stays inside the
    observed support. ``supportMin``/``supportMax`` are the outer edges of that
    trimmed range (also percentiles 0 and 100).
    """
    if bin_width <= 0:
        raise ValueError("bin_width must be positive")
    if alpha < 0:
        raise ValueError("alpha must be non-negative")
    if percentile_step <= 0 or 100 % percentile_step != 0:
        raise ValueError("percentile_step must be a positive divisor of 100")
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
    smoothed = [count + alpha for count in trimmed]
    total = sum(smoothed)
    if total <= 0:
        raise ValueError("smoothed histogram mass must be positive")

    support_min = first * bin_width
    support_max = (last + 1) * bin_width

    # CDF knots: (distance, cumulative probability) at each bin's right edge,
    # starting from support_min at probability 0.
    distances = [support_min]
    cumulatives = [0.0]
    running = 0.0
    for offset, mass in enumerate(smoothed):
        running += mass
        distances.append((first + offset + 1) * bin_width)
        cumulatives.append(running / total)
    cumulatives[-1] = 1.0

    percentile_count = (100 // percentile_step) + 1
    percentiles: list[float] = []
    for index in range(percentile_count):
        target = index * percentile_step / 100.0
        percentiles.append(_invert_cdf(distances, cumulatives, target))

    resolved_sample_count = sample_count if sample_count is not None else sum(trimmed)
    return SmoothedMetricDistribution(
        sample_count=resolved_sample_count,
        support_min=round(support_min, 1),
        support_max=round(support_max, 1),
        percentiles=tuple(round(value, 1) for value in percentiles),
        percentile_step=percentile_step,
    )


def distill_layout_distributions_from_report(
    report: Mapping[str, Any],
    *,
    alpha: float = DEFAULT_LAPLACE_ALPHA,
    percentile_step: int = DEFAULT_PERCENTILE_STEP,
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
                alpha=alpha,
                percentile_step=percentile_step,
                sample_count=int(center_summary["n"]) if "n" in center_summary else None,
            ),
            neighbor_separation=distill_metric_from_histogram(
                neighbor_counts,
                bin_width=bin_width,
                alpha=alpha,
                percentile_step=percentile_step,
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
        smoothing_method=SMOOTHING_METHOD_LAPLACE,
        laplace_alpha=alpha,
        percentile_step=percentile_step,
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
        "smoothing": {
            "method": asset.smoothing_method,
            "alpha": asset.laplace_alpha,
        },
        "percentileStep": asset.percentile_step,
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
    smoothing = raw.get("smoothing")
    if not isinstance(smoothing, Mapping):
        raise ValueError("smoothing must be an object")
    method = smoothing.get("method")
    if method != SMOOTHING_METHOD_LAPLACE:
        raise ValueError(f"unsupported smoothing method {method!r}")
    alpha = float(smoothing["alpha"])
    percentile_step = int(raw.get("percentileStep", DEFAULT_PERCENTILE_STEP))
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
                percentile_step=percentile_step,
            ),
            neighbor_separation=_metric_from_json(
                category_raw.get("neighborSeparation"),
                field_name=f"categories.{key}.neighborSeparation",
                percentile_step=percentile_step,
            ),
        )

    source = raw.get("source", {})
    if source is not None and not isinstance(source, Mapping):
        raise ValueError("source must be an object when present")

    return LayoutDistributionsAsset(
        schema_version=SCHEMA_VERSION,
        bin_width_ly=bin_width,
        smoothing_method=SMOOTHING_METHOD_LAPLACE,
        laplace_alpha=alpha,
        percentile_step=percentile_step,
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
    return asset_path


def _metric_to_json(metric: SmoothedMetricDistribution) -> dict[str, Any]:
    return {
        "sampleCount": metric.sample_count,
        "supportMin": metric.support_min,
        "supportMax": metric.support_max,
        "percentiles": list(metric.percentiles),
    }


def _metric_from_json(
    raw: object,
    *,
    field_name: str,
    percentile_step: int,
) -> SmoothedMetricDistribution:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{field_name} must be an object")
    percentiles_raw = raw.get("percentiles")
    if not isinstance(percentiles_raw, list) or not percentiles_raw:
        raise ValueError(f"{field_name}.percentiles must be a non-empty array")
    expected_len = (100 // percentile_step) + 1
    if len(percentiles_raw) != expected_len:
        raise ValueError(
            f"{field_name}.percentiles must have length {expected_len} "
            f"for percentileStep={percentile_step}"
        )
    support_min = float(raw["supportMin"])
    support_max = float(raw["supportMax"])
    if support_max < support_min:
        raise ValueError(f"{field_name}: supportMax must be >= supportMin")
    return SmoothedMetricDistribution(
        sample_count=int(raw["sampleCount"]),
        support_min=support_min,
        support_max=support_max,
        percentiles=tuple(float(value) for value in percentiles_raw),
        percentile_step=percentile_step,
    )


def _invert_cdf(
    distances: list[float],
    cumulatives: list[float],
    target: float,
) -> float:
    if target <= 0:
        return distances[0]
    if target >= 1:
        return distances[-1]
    for index in range(1, len(cumulatives)):
        upper_p = cumulatives[index]
        if target > upper_p:
            continue
        lower_p = cumulatives[index - 1]
        lower_d = distances[index - 1]
        upper_d = distances[index]
        if upper_p <= lower_p:
            return upper_d
        fraction = (target - lower_p) / (upper_p - lower_p)
        return lower_d + fraction * (upper_d - lower_d)
    return distances[-1]

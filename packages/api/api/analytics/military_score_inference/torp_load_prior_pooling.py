"""Pooled torpedo-load priors shared across per-type aggregate solver actions."""

from __future__ import annotations

from api.analytics.military_score_inference.aggregate_action_registry import (
    SHIP_TORPS_LOADED_ACTION_PREFIX,
    SHIP_TORPS_LOADED_ANY_PRIOR_KEY,
)
from api.analytics.military_score_inference.prior_weights_asset import HistogramAggregate

__all__ = [
    "SHIP_TORPS_LOADED_ANY_PRIOR_KEY",
    "any_torp_load_histogram_for_band",
    "synthesize_any_torp_load_histogram",
]


def synthesize_any_torp_load_histogram(
    band_tables: dict[str, HistogramAggregate],
    eligible_torp_ids: frozenset[int],
) -> HistogramAggregate:
    """Approximate any-torp histogram from per-type tables when mining omitted the pooled key."""
    histograms: list[dict[int, float]] = []
    for torp_id in sorted(eligible_torp_ids):
        aggregate = band_tables.get(f"{SHIP_TORPS_LOADED_ACTION_PREFIX}{torp_id}")
        if aggregate is not None:
            histograms.append(aggregate.histogram)
    if not histograms:
        raise ValueError("cannot synthesize any-torp histogram without per-type tables")

    sample_totals = [sum(histogram.values()) for histogram in histograms]
    total_samples = max(sample_totals)
    if len(set(sample_totals)) == 1:
        pooled: dict[int, float] = {}
        for histogram in histograms:
            for magnitude, count in histogram.items():
                if magnitude > 0:
                    pooled[magnitude] = pooled.get(magnitude, 0.0) + count

        positive_samples = sum(pooled.values())
        max_per_type_positive = max(
            sum(count for magnitude, count in histogram.items() if magnitude > 0)
            for histogram in histograms
        )
        if positive_samples > total_samples:
            scale = max_per_type_positive / positive_samples if positive_samples else 1.0
            pooled = {magnitude: count * scale for magnitude, count in pooled.items()}
            positive_samples = max_per_type_positive

        pooled[0] = total_samples - positive_samples
        return HistogramAggregate(histogram=pooled)

    rate_sums: dict[int, float] = {}
    for histogram in histograms:
        histogram_total = sum(histogram.values())
        for magnitude, count in histogram.items():
            rate_sums[magnitude] = rate_sums.get(magnitude, 0.0) + count / histogram_total
    pooled = {
        magnitude: (rate / len(histograms)) * total_samples for magnitude, rate in rate_sums.items()
    }
    return HistogramAggregate(histogram=_integerize_histogram_counts(pooled))


def _integerize_histogram_counts(pooled: dict[int, float]) -> dict[int, float]:
    rounded = {magnitude: float(int(round(count))) for magnitude, count in pooled.items()}
    total = sum(rounded.values())
    target = round(sum(pooled.values()))
    if total == target or not rounded:
        return rounded
    # Keep total mass stable when rate-averaging produces rounding drift.
    magnitude = max(rounded, key=rounded.get)
    rounded[magnitude] += target - total
    return rounded


def any_torp_load_histogram_for_band(
    band_tables: dict[str, HistogramAggregate],
    eligible_torp_ids: frozenset[int],
) -> HistogramAggregate:
    mined = band_tables.get(SHIP_TORPS_LOADED_ANY_PRIOR_KEY)
    if mined is not None:
        return mined
    return synthesize_any_torp_load_histogram(band_tables, eligible_torp_ids)

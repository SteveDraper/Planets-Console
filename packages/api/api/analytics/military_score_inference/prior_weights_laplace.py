"""Laplace smoothing and wildcard expansion for inference build priors."""

from __future__ import annotations

import math
from typing import Any

from api.analytics.military_score_inference.inference_probability_scale import (
    INFERENCE_PROBABILITY_WEIGHT_SCALE,
)

WILDCARD_COUNT_KEY = "*"

LAPLACE_ALPHA = 1
IMPLICIT_UNIFORM_PSEUDO_COUNT = 1.0


def laplace_log_weight(count: float, *, total: float, cell_count: int, scale: int) -> int:
    probability = (count + LAPLACE_ALPHA) / (total + LAPLACE_ALPHA * cell_count)
    return round(scale * math.log(probability))


def counts_to_log_weights(
    counts: dict[Any, float],
    *,
    scale: int = INFERENCE_PROBABILITY_WEIGHT_SCALE,
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


def finalize_counts_for_laplace(counts: dict[Any, float]) -> dict[Any, float]:
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

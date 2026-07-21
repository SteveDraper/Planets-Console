"""Per-row option-set softmax masses for fleet belief and max-tech gating (#253).

Glossary: CONTEXT.md (**Inference fleet launcher belief mass**, **Inference fleet
option-set mass threshold**). Softmax uses ``solution_rank_weight /
INFERENCE_PROBABILITY_WEIGHT_SCALE`` as the log-score; beam-only / no-tube sets
participate so they can starve tube types.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from api.analytics.fleet.field_constraints import known_positive_component_id
from api.analytics.fleet.types import FleetBuildOptionSet, FleetShipRecord
from api.concepts.inference_probability_scale import (
    INFERENCE_PROBABILITY_WEIGHT_SCALE,
)

__all__ = [
    "DEFAULT_OPTION_SET_MASS_THRESHOLD",
    "launcher_belief_mass_by_torp_id_from_records",
    "option_set_softmax_probabilities",
    "row_option_set_softmax_probabilities",
]

DEFAULT_OPTION_SET_MASS_THRESHOLD = 0.25


def option_set_softmax_probabilities(
    option_sets: Sequence[FleetBuildOptionSet],
) -> tuple[float, ...]:
    """Softmax probabilities for one row's option sets (empty → empty tuple)."""
    if not option_sets:
        return ()
    scores = [
        option_set.solution_rank_weight / INFERENCE_PROBABILITY_WEIGHT_SCALE
        for option_set in option_sets
    ]
    max_score = max(scores)
    exps = [math.exp(score - max_score) for score in scores]
    total = sum(exps)
    if total <= 0.0:
        uniform = 1.0 / len(option_sets)
        return tuple(uniform for _ in option_sets)
    return tuple(value / total for value in exps)


def row_option_set_softmax_probabilities(record: FleetShipRecord) -> tuple[float, ...]:
    return option_set_softmax_probabilities(record.build_option_sets)


def launcher_belief_mass_by_torp_id_from_records(
    records: Iterable[FleetShipRecord],
    *,
    active_only: bool = True,
) -> dict[int, float]:
    """Player-level launcher belief mass per torp id (max over active rows).

    Hard support: known positive ``fields.launchers`` → mass 1 for that id from
    the row (option sets never count as hard). Soft support on ambiguous rows:
    sum of softmax probabilities of option sets with ``torp_id == t``.
    """
    masses: dict[int, float] = {}
    for record in records:
        if active_only and record.disposition != "active":
            continue
        for torp_id, mass in _row_launcher_belief_masses(record).items():
            previous = masses.get(torp_id)
            if previous is None or mass > previous:
                masses[torp_id] = mass
    return masses


def _row_launcher_belief_masses(record: FleetShipRecord) -> dict[int, float]:
    known_launcher = known_positive_component_id(record.fields.launchers)
    if known_launcher is not None:
        return {known_launcher: 1.0}

    probabilities = row_option_set_softmax_probabilities(record)
    if not probabilities:
        return {}

    soft_masses: dict[int, float] = {}
    for option_set, probability in zip(record.build_option_sets, probabilities, strict=True):
        torp_id = option_set.torp_id
        if not isinstance(torp_id, int) or isinstance(torp_id, bool) or torp_id <= 0:
            continue
        soft_masses[torp_id] = soft_masses.get(torp_id, 0.0) + probability
    return soft_masses

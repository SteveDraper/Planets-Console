"""Ranking heuristics for military score build inference CP-SAT objective and constraints."""

from __future__ import annotations

from dataclasses import dataclass, field

from api.analytics.military_score_inference.aggregate_action_registry import (
    SHIP_TORPS_LOADED_ACTION_PREFIX,
    lookup_aggregate_action_spec,
    magnitude_bin_index,
)
from api.analytics.military_score_inference.inference_probability_scale import (
    INFERENCE_PROBABILITY_WEIGHT_SCALE,
)
from api.analytics.military_score_inference.models import (
    InferenceSolutionShipBuild,
    ProbabilityBucket,
    ShipBuildCombo,
)

EVIL_EMPIRE_FREE_STARBASE_FIGHTERS_ID = "evil_empire_free_starbase_fighters"

TORPEDO_LOADS_SUPERCLASS = "torpedo_loads"
FIGHTER_CHANNEL_SUPERCLASS = "fighter_channel"


def _default_parsimony_per_active_slack_type() -> int:
    return -(INFERENCE_PROBABILITY_WEIGHT_SCALE // 2)


def _default_partial_weapon_slot_penalty_per_line() -> int:
    return -(INFERENCE_PROBABILITY_WEIGHT_SCALE // 4)


def _default_tier_overflow_marginal_weight() -> int:
    return INFERENCE_PROBABILITY_WEIGHT_SCALE // 2


@dataclass(frozen=True)
class InferenceRankingHeuristics:
    parsimony_per_active_slack_type: int = field(
        default_factory=_default_parsimony_per_active_slack_type
    )
    partial_weapon_slot_penalty_per_line: int = field(
        default_factory=_default_partial_weapon_slot_penalty_per_line
    )
    tier_overflow_marginal_weight: int = field(
        default_factory=_default_tier_overflow_marginal_weight
    )
    torpedo_load_diversity_cap: int = 2
    fighter_channel_diversity_cap: int = 2


@dataclass(frozen=True)
class TierOverflowBand:
    admission_cap: int
    current_cap: int
    marginal_weight: int


def is_parsimony_eligible_slack_action(action_id: str) -> bool:
    if action_id == EVIL_EMPIRE_FREE_STARBASE_FIGHTERS_ID:
        return False
    spec = lookup_aggregate_action_spec(action_id)
    return spec is not None and spec.is_fine_grained_slack


def max_marginal_weight(buckets: tuple[ProbabilityBucket, ...]) -> int:
    return max(bucket.marginal_weight for bucket in buckets)


def ranking_penalty_from_marginal_weight(
    marginal_weight: int,
    *,
    max_marginal_weight: int,
) -> int:
    """Map a legacy positive marginal weight to a ranking penalty (lower is better)."""
    return max_marginal_weight - marginal_weight


def active_ranking_bin_index(
    count: int,
    buckets: tuple[ProbabilityBucket, ...],
) -> int | None:
    """Return the index of the single magnitude bin for a positive aggregate count."""
    if count <= 0:
        return None
    return magnitude_bin_index(count, buckets)


def active_ranking_bin_indicators(
    count: int,
    buckets: tuple[ProbabilityBucket, ...],
) -> tuple[int, ...]:
    active_index = active_ranking_bin_index(count, buckets)
    return tuple(1 if index == active_index else 0 for index in range(len(buckets)))


def compute_bin_penalty_objective_contribution(
    action_counts: dict[str, int],
    buckets_by_action_id: dict[str, tuple[ProbabilityBucket, ...]],
) -> int:
    """Subtract one rescaled bin penalty per bucketed action (not per unit in the bin)."""
    contribution = 0
    for action_id, buckets in buckets_by_action_id.items():
        active_index = active_ranking_bin_index(action_counts.get(action_id, 0), buckets)
        if active_index is None:
            continue
        penalty = ranking_penalty_from_marginal_weight(
            buckets[active_index].marginal_weight,
            max_marginal_weight=max_marginal_weight(buckets),
        )
        contribution -= penalty
    return contribution


def build_tier_aware_probability_buckets(
    base_buckets: tuple[ProbabilityBucket, ...],
    *,
    admission_cap: int | None,
    current_cap: int,
    overflow_marginal_weight: int,
) -> tuple[tuple[ProbabilityBucket, ...], TierOverflowBand | None]:
    if admission_cap is None or current_cap <= admission_cap:
        return base_buckets, None
    return base_buckets, TierOverflowBand(
        admission_cap=admission_cap,
        current_cap=current_cap,
        marginal_weight=overflow_marginal_weight,
    )


def partial_weapon_slot_penalty_for_fit(
    *,
    beam_count: int,
    launcher_count: int,
    hull_beam_slots: int,
    hull_launcher_slots: int,
    heuristics: InferenceRankingHeuristics,
) -> int:
    """Penalty when a hull uses some but not all of an available weapon slot line."""
    penalty = 0
    per_line = heuristics.partial_weapon_slot_penalty_per_line
    if hull_beam_slots > 0 and 0 < beam_count < hull_beam_slots:
        penalty += per_line
    if hull_launcher_slots > 0 and 0 < launcher_count < hull_launcher_slots:
        penalty += per_line
    return penalty


def compute_partial_weapon_slot_penalty_contribution(
    ship_builds: tuple[InferenceSolutionShipBuild, ...],
    combo_by_id: dict[str, ShipBuildCombo],
    heuristics: InferenceRankingHeuristics,
) -> int:
    contribution = 0
    for ship_build in ship_builds:
        combo = combo_by_id[ship_build.combo_id]
        per_ship_penalty = partial_weapon_slot_penalty_for_fit(
            beam_count=combo.beam_count,
            launcher_count=combo.launcher_count,
            hull_beam_slots=combo.hull_beam_slots,
            hull_launcher_slots=combo.hull_launcher_slots,
            heuristics=heuristics,
        )
        contribution += per_ship_penalty * ship_build.count
    return contribution


def compute_parsimony_objective_contribution(
    action_counts: dict[str, int],
    heuristics: InferenceRankingHeuristics,
) -> int:
    active_slack_types = sum(
        1
        for action_id, count in action_counts.items()
        if count > 0 and is_parsimony_eligible_slack_action(action_id)
    )
    return active_slack_types * heuristics.parsimony_per_active_slack_type


def compute_overflow_objective_contribution(
    action_counts: dict[str, int],
    tier_overflow_by_action_id: dict[str, TierOverflowBand],
) -> int:
    contribution = 0
    for action_id, overflow_band in tier_overflow_by_action_id.items():
        count = action_counts.get(action_id, 0)
        if count > overflow_band.admission_cap:
            contribution -= overflow_band.marginal_weight
    return contribution


def torpedo_load_action_ids(catalog_action_ids: frozenset[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            action_id
            for action_id in catalog_action_ids
            if action_id.startswith(SHIP_TORPS_LOADED_ACTION_PREFIX)
        )
    )


def fighter_channel_action_ids(catalog_action_ids: frozenset[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            action_id
            for action_id in catalog_action_ids
            if (spec := lookup_aggregate_action_spec(action_id)) is not None
            and spec.is_fighter_channel_member
        )
    )


def ranking_heuristics_diagnostics_payload(
    heuristics: InferenceRankingHeuristics,
    *,
    admission_caps_by_action_id: dict[str, int],
) -> dict[str, object]:
    return {
        "parsimonyPerActiveSlackType": heuristics.parsimony_per_active_slack_type,
        "partialWeaponSlotPenaltyPerLine": heuristics.partial_weapon_slot_penalty_per_line,
        "tierOverflowMarginalWeight": heuristics.tier_overflow_marginal_weight,
        "diversityCaps": [
            {"superclass": TORPEDO_LOADS_SUPERCLASS, "cap": heuristics.torpedo_load_diversity_cap},
            {
                "superclass": FIGHTER_CHANNEL_SUPERCLASS,
                "cap": heuristics.fighter_channel_diversity_cap,
            },
        ],
        "admissionCaps": dict(admission_caps_by_action_id),
    }


def diversity_caps_applied_payload(
    heuristics: InferenceRankingHeuristics,
    catalog_action_ids: frozenset[str],
) -> list[dict[str, object]]:
    applied: list[dict[str, object]] = []
    torpedo_ids = torpedo_load_action_ids(catalog_action_ids)
    if torpedo_ids:
        applied.append(
            {
                "superclass": TORPEDO_LOADS_SUPERCLASS,
                "cap": heuristics.torpedo_load_diversity_cap,
                "memberActionIds": list(torpedo_ids),
            }
        )
    fighter_ids = fighter_channel_action_ids(catalog_action_ids)
    if fighter_ids:
        applied.append(
            {
                "superclass": FIGHTER_CHANNEL_SUPERCLASS,
                "cap": heuristics.fighter_channel_diversity_cap,
                "memberActionIds": list(fighter_ids),
            }
        )
    return applied

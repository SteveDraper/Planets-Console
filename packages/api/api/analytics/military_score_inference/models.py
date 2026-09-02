"""Data contracts for military score build inference."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from api.analytics.military_score_inference.ranking_heuristics import (
        InferenceRankingHeuristics,
        TierOverflowBand,
    )


def _default_ranking_heuristics() -> InferenceRankingHeuristics:
    from api.analytics.military_score_inference.ranking_heuristics import InferenceRankingHeuristics

    return InferenceRankingHeuristics()


# After first maximize Z*, further structural solves only accept ranking objectives
# in [Z* - T, sliding max]. Shared by InferenceProblem, ActionCatalog, and tier YAML.
DEFAULT_NEAR_BEST_OBJECTIVE_THRESHOLD = 250


@dataclass(frozen=True)
class InferenceObservation:
    player_id: int
    turn: int
    military_delta_2x: int
    warship_delta: int
    freighter_delta: int
    priority_point_delta: int
    starbases_owned: int
    is_after_ship_limit: bool
    military_partition_slack_2x: int = 0
    scoreboard_delta_source: str = "reported_change_fields"
    planet_delta: int = 0
    starbase_delta: int = 0


@dataclass(frozen=True)
class CandidateAction:
    id: str
    label: str
    score_delta_2x: int
    warship_delta: int = 0
    freighter_delta: int = 0
    priority_point_delta: int = 0
    build_slot_usage: int = 0
    lower_bound: int = 0
    upper_bound: int = 0
    score_delta_2x_min: int | None = None
    score_delta_2x_max: int | None = None
    counterparty_player_id: int | None = None
    prior_warship_usage: int = 0
    prior_freighter_usage: int = 0
    # Prior-fleet departure group identity shared across loss/gift/trade families;
    # None for actions that do not consume a prior-fleet record.
    prior_group_key: str | None = None
    # Set when warship and freighter are exclusive alternatives for one transfer.
    exclusive_class_group: str | None = None


def candidate_action_has_military_interval(action: CandidateAction) -> bool:
    """True when the catalog gives this action a proper military envelope."""
    return (
        action.score_delta_2x_min is not None
        and action.score_delta_2x_max is not None
        and action.score_delta_2x_min != action.score_delta_2x_max
    )


def candidate_military_subtotal_bounds_2x(action: CandidateAction, count: int) -> tuple[int, int]:
    """Inclusive catalog military 2x for ``count`` units of ``action``."""
    if candidate_action_has_military_interval(action):
        lo = action.score_delta_2x_min
        hi = action.score_delta_2x_max
        if lo is None or hi is None:
            point = action.score_delta_2x * count
            return point, point
        if lo > hi:
            lo, hi = hi, lo
        return lo * count, hi * count
    point = action.score_delta_2x * count
    return point, point


class MagnitudeCountBounds(Protocol):
    """Structural type for magnitude-bin count ranges (bounds or full buckets)."""

    lower_count: int
    upper_count: int


def magnitude_bin_index(magnitude: int, bin_bounds: tuple[MagnitudeCountBounds, ...]) -> int:
    """Return the index of the magnitude bin containing a non-negative count.

    The leading ``none`` bin ``[0, 0]`` matches ``magnitude == 0``; counts above the
    top bin fall through to the last bin.
    """
    for index, bound in enumerate(bin_bounds):
        if bound.lower_count <= magnitude <= bound.upper_count:
            return index
    return len(bin_bounds) - 1


@dataclass(frozen=True)
class ProbabilityBinBounds:
    """Solver magnitude-bin geometry (labels and count ranges only)."""

    label: str
    lower_count: int
    upper_count: int


@dataclass(frozen=True)
class ProbabilityBucket:
    label: str
    lower_count: int
    upper_count: int
    marginal_weight: int


def probability_buckets_from_bin_bounds(
    bounds: tuple[ProbabilityBinBounds, ...],
    marginal_weights: tuple[int, ...],
) -> tuple[ProbabilityBucket, ...]:
    if len(bounds) != len(marginal_weights):
        raise ValueError("bin bounds and marginal weight count must match")
    return tuple(
        ProbabilityBucket(
            label=bound.label,
            lower_count=bound.lower_count,
            upper_count=bound.upper_count,
            marginal_weight=weight,
        )
        for bound, weight in zip(bounds, marginal_weights, strict=True)
    )


@dataclass(frozen=True)
class ShipBuildCombo:
    combo_id: str
    hull_id: int
    engine_id: int
    beam_id: int | None
    torp_id: int | None
    beam_count: int
    launcher_count: int
    labels: tuple[str, ...]
    score_delta_2x: int
    warship_delta: int = 0
    freighter_delta: int = 0
    build_slot_usage: int = 1
    lower_bound: int = 0
    upper_bound: int = 0
    probability_weight: int = 0
    hull_beam_slots: int = 0
    hull_launcher_slots: int = 0


@dataclass(frozen=True)
class InferenceProblem:
    observation: InferenceObservation
    aggregate_actions: tuple[CandidateAction, ...]
    race_id: int | None = None
    ship_build_combos: tuple[ShipBuildCombo, ...] = ()
    policy_step_id: str = ""
    policy_step_index: int = 0
    probability_buckets_by_action_id: dict[str, tuple[ProbabilityBucket, ...]] = field(
        default_factory=dict
    )
    max_solutions: int = 20
    time_limit_seconds: float = 20.0
    enforce_priority_point_constraint: bool = False
    enforce_idle_dock_pp_equality: bool = False
    prior_warship_departure_cap: int = 0
    prior_freighter_departure_cap: int = 0
    prior_departure_group_caps: dict[str, int] = field(default_factory=dict)
    acquired_warship_cap: int | None = None  # None = no cap; 0 = hard disallow
    acquired_freighter_cap: int | None = None
    acquired_ship_cap: int | None = None
    military_score_alpha: int = 0
    ranking_heuristics: InferenceRankingHeuristics = field(
        default_factory=_default_ranking_heuristics
    )
    admission_caps_by_action_id: dict[str, int] = field(default_factory=dict)
    tier_overflow_by_action_id: dict[str, TierOverflowBand] = field(default_factory=dict)
    # Within-tier near-best ranking band width T (always applied after first maximize).
    near_best_objective_threshold: int = DEFAULT_NEAR_BEST_OBJECTIVE_THRESHOLD


@dataclass(frozen=True)
class InferenceSolutionAction:
    action_id: str
    label: str
    count: int
    counterparty_player_id: int | None = None


@dataclass(frozen=True)
class InferenceSolutionShipBuild:
    combo_id: str
    label: str
    count: int
    hull_id: int | None = None
    engine_id: int | None = None
    beam_id: int | None = None
    torp_id: int | None = None
    beam_count: int = 0
    launcher_count: int = 0


@dataclass(frozen=True)
class InferenceSolution:
    objective_value: int
    actions: tuple[InferenceSolutionAction, ...]
    ship_builds: tuple[InferenceSolutionShipBuild, ...] = ()


@dataclass(frozen=True)
class InferenceResult:
    status: str
    solutions: tuple[InferenceSolution, ...]
    diagnostics: dict[str, object]

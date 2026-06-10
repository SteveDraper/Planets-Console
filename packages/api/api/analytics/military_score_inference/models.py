"""Data contracts for military score build inference."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.analytics.military_score_inference.ranking_heuristics import (
        InferenceRankingHeuristics,
        TierOverflowBand,
    )


def _default_ranking_heuristics() -> InferenceRankingHeuristics:
    from api.analytics.military_score_inference.ranking_heuristics import InferenceRankingHeuristics

    return InferenceRankingHeuristics()


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
    probability_weight: int = 0


@dataclass(frozen=True)
class ProbabilityBucket:
    label: str
    lower_count: int
    upper_count: int
    marginal_weight: int


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
    ship_build_combos: tuple[ShipBuildCombo, ...] = ()
    policy_step_id: str = ""
    policy_step_index: int = 0
    probability_buckets_by_action_id: dict[str, tuple[ProbabilityBucket, ...]] = field(
        default_factory=dict
    )
    max_solutions: int = 20
    time_limit_seconds: float = 20.0
    enforce_priority_point_constraint: bool = False
    military_score_alpha: int = 0
    ranking_heuristics: InferenceRankingHeuristics = field(
        default_factory=_default_ranking_heuristics
    )
    admission_caps_by_action_id: dict[str, int] = field(default_factory=dict)
    tier_overflow_by_action_id: dict[str, TierOverflowBand] = field(default_factory=dict)


@dataclass(frozen=True)
class InferenceSolutionAction:
    action_id: str
    label: str
    count: int


@dataclass(frozen=True)
class InferenceSolutionShipBuild:
    combo_id: str
    label: str
    count: int
    hull_id: int
    engine_id: int
    beam_id: int | None
    torp_id: int | None
    beam_count: int
    launcher_count: int


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

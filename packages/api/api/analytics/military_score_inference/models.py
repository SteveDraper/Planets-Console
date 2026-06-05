"""Data contracts for military score build inference."""

from dataclasses import dataclass, field


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


@dataclass(frozen=True)
class InferenceProblem:
    observation: InferenceObservation
    aggregate_actions: tuple[CandidateAction, ...]
    ship_build_combos: tuple[ShipBuildCombo, ...] = ()
    ship_build_tier: int = 0
    probability_buckets_by_action_id: dict[str, tuple[ProbabilityBucket, ...]] = field(
        default_factory=dict
    )
    max_solutions: int = 20
    time_limit_seconds: float = 20.0
    enforce_priority_point_constraint: bool = False


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

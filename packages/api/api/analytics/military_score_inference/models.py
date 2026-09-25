"""Data contracts for military score build inference."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from api.analytics.military_score_inference.military_score_window import (
    ExactMilitaryScoreWindow,
    MilitaryScoreWindow,
    military_window_alpha,
    military_window_overshoot_cap_2x,
)
from api.analytics.military_score_inference.uncharacterized_roster_types import (
    ExactSetDeparturePin,
    LatticeSignature,
    PlaceholderDeparture,
    UnknownLossLeftover,
)

if TYPE_CHECKING:
    from ortools.sat.python import cp_model

    from api.analytics.military_score_inference.ranking_heuristics import (
        InferenceRankingHeuristics,
        TierOverflowBand,
    )

# Spent deterministic time may land just short of the clip and still count as exhaustion.
_DETERMINISTIC_TIME_SLACK = 1e-9


@dataclass(frozen=True)
class NextSolveClip:
    """Clip for the next ``Solve()``, or a stop when nothing remains to apply."""

    clip: SolveClip | None
    time_limited: bool = False
    hang_fuse: bool = False


@dataclass(frozen=True)
class SolveClipDecision:
    """Clip-owned reading of one ``Solve()`` status.

    Band exhaustion, infeasibility, and cancel stay with the search loop.
    """

    time_limited: bool = False
    hang_fuse: bool = False


def _cp_solver_status():
    from ortools.sat.python import cp_model

    return cp_model


@dataclass(frozen=True)
class EffortSolveClip:
    """Stream Solve clip: deterministic-time allowance; wall only for hang fuse."""

    max_deterministic_time: float
    hang_fuse_remaining: float | None = None

    def is_exhausted(self) -> bool:
        return self.max_deterministic_time <= 0

    def problem_time_limit_seconds(self) -> float:
        """Problem wall field. Effort is not stored there."""
        return 0.0

    def apply_to_solver(self, solver: cp_model.CpSolver) -> None:
        solver.parameters.max_deterministic_time = max(0.0, self.max_deterministic_time)
        if self.hang_fuse_remaining is not None:
            solver.parameters.max_time_in_seconds = max(0.0, self.hang_fuse_remaining)

    def next_solve(
        self,
        *,
        effort_spent: float,
        elapsed_seconds: float,
        solve_wall_seconds: float = 0.0,
    ) -> NextSolveClip:
        """Remaining effort clip, or a stop when effort or the fuse is already gone.

        ``elapsed_seconds`` is unused. Fuse remainder is this clip's hang fuse
        minus Solve-only wall already spent (not inter-solve Python time).
        """
        del elapsed_seconds
        remaining_fuse: float | None = None
        if self.hang_fuse_remaining is not None:
            remaining_fuse = self.hang_fuse_remaining - solve_wall_seconds
            if remaining_fuse <= 0:
                return NextSolveClip(clip=None, hang_fuse=True)
        remaining_effort = self.max_deterministic_time - effort_spent
        if remaining_effort <= 0:
            return NextSolveClip(clip=None, time_limited=True)
        return NextSolveClip(
            clip=EffortSolveClip(
                max_deterministic_time=remaining_effort,
                hang_fuse_remaining=remaining_fuse,
            )
        )

    def after_solve(
        self,
        *,
        solver_status: int,
        effort_spent: float,
        solve_wall_seconds: float,
        elapsed_seconds: float,
        has_structural_hits: bool,
    ) -> SolveClipDecision:
        """Read effort exhaustion, hang fuse, or UNKNOWN-with-hits.

        A fuse hit wins over effort exhaustion (including when both trip).
        UNKNOWN plus hits is exhaustion even when ``deterministic_time()`` is
        short of this clip and the fuse has not hit. Numeric exhaustion on a
        successful status does not by itself end the search; the loop records
        that hit and stops on the next ``next_solve``.
        """
        del elapsed_seconds
        cp_model = _cp_solver_status()
        if self.hang_fuse_remaining is not None and solve_wall_seconds >= self.hang_fuse_remaining:
            return SolveClipDecision(hang_fuse=True)
        time_limited = effort_spent + _DETERMINISTIC_TIME_SLACK >= self.max_deterministic_time
        if solver_status == cp_model.UNKNOWN and has_structural_hits:
            return SolveClipDecision(time_limited=True)
        return SolveClipDecision(time_limited=time_limited)


@dataclass(frozen=True)
class WallSolveClip:
    """Batch (or probe) Solve clip: wall-clock case / slice limit."""

    max_time_in_seconds: float

    def is_exhausted(self) -> bool:
        return self.max_time_in_seconds <= 0

    def problem_time_limit_seconds(self) -> float:
        return self.max_time_in_seconds

    def apply_to_solver(self, solver: cp_model.CpSolver) -> None:
        solver.parameters.max_time_in_seconds = max(0.0, self.max_time_in_seconds)

    def next_solve(
        self,
        *,
        effort_spent: float,
        elapsed_seconds: float,
        solve_wall_seconds: float = 0.0,
    ) -> NextSolveClip:
        """Remaining wall clip, or a stop when the slice clock is spent."""
        del effort_spent, solve_wall_seconds
        remaining_seconds = self.max_time_in_seconds - elapsed_seconds
        if remaining_seconds <= 0:
            return NextSolveClip(clip=None, time_limited=True)
        return NextSolveClip(clip=WallSolveClip(max_time_in_seconds=remaining_seconds))

    def after_solve(
        self,
        *,
        solver_status: int,
        effort_spent: float,
        solve_wall_seconds: float,
        elapsed_seconds: float,
        has_structural_hits: bool,
    ) -> SolveClipDecision:
        """Read wall exhaustion on FEASIBLE, or UNKNOWN-with-hits.

        FEASIBLE at the wall limit marks the row time-limited and still keeps
        the hit. The next ``next_solve`` is what leaves the loop.
        """
        del effort_spent, solve_wall_seconds
        cp_model = _cp_solver_status()
        if solver_status == cp_model.UNKNOWN and has_structural_hits:
            return SolveClipDecision(time_limited=True)
        time_limited = (
            solver_status == cp_model.FEASIBLE and elapsed_seconds >= self.max_time_in_seconds
        )
        return SolveClipDecision(time_limited=time_limited)


SolveClip = EffortSolveClip | WallSolveClip


def effective_solve_clip(
    *,
    solve_clip: SolveClip | None,
    time_limit_seconds: float,
) -> SolveClip:
    """Return the clip to use; default is a batch wall clip from ``time_limit_seconds``."""
    if solve_clip is not None:
        return solve_clip
    return WallSolveClip(max_time_in_seconds=time_limit_seconds)


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
    # Typed Solve clip. When unset, the search loop uses WallSolveClip(time_limit_seconds).
    solve_clip: EffortSolveClip | WallSolveClip | None = None
    enforce_priority_point_constraint: bool = False
    enforce_idle_dock_pp_equality: bool = False
    prior_warship_departure_cap: int = 0
    prior_freighter_departure_cap: int = 0
    prior_departure_group_caps: dict[str, int] = field(default_factory=dict)
    acquired_warship_cap: int | None = None  # None = no cap; 0 = hard disallow
    acquired_freighter_cap: int | None = None
    acquired_ship_cap: int | None = None
    military_score_window: MilitaryScoreWindow = field(default_factory=ExactMilitaryScoreWindow)
    ranking_heuristics: InferenceRankingHeuristics = field(
        default_factory=_default_ranking_heuristics
    )
    admission_caps_by_action_id: dict[str, int] = field(default_factory=dict)
    tier_overflow_by_action_id: dict[str, TierOverflowBand] = field(default_factory=dict)
    # Within-tier near-best ranking band width T (always applied after first maximize).
    near_best_objective_threshold: int = DEFAULT_NEAR_BEST_OBJECTIVE_THRESHOLD

    @property
    def military_score_alpha(self) -> int:
        return military_window_alpha(self.military_score_window)

    @property
    def military_overshoot_cap_2x(self) -> int | None:
        return military_window_overshoot_cap_2x(self.military_score_window)


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


ShipFirstFamily = Literal["mine_overshoot", "ammo_top_up"]


@dataclass(frozen=True)
class InferenceSolution:
    objective_value: int
    actions: tuple[InferenceSolutionAction, ...]
    ship_builds: tuple[InferenceSolutionShipBuild, ...] = ()
    ship_first_family: ShipFirstFamily | None = None


@dataclass(frozen=True)
class InferenceResult:
    status: str
    solutions: tuple[InferenceSolution, ...]
    diagnostics: dict[str, object]
    placeholders: tuple[dict[str, object], ...] = ()
    placeholder_departures: tuple[PlaceholderDeparture, ...] = ()
    leftover: UnknownLossLeftover | None = None
    lattice_signatures: tuple[LatticeSignature, ...] = ()
    departure_pins: tuple[ExactSetDeparturePin, ...] = ()

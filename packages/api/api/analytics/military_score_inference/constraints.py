"""Hard CP-SAT constraints and matching diagnostics for military score build inference."""

from dataclasses import dataclass

from ortools.sat.python import cp_model

from api.analytics.military_score_inference.accelerated_start import scoreboard_host_turn
from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.inference_objective import add_count_active_indicator
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    InferenceSolution,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.ranking_heuristics import (
    InferenceRankingHeuristics,
    diversity_caps_applied_payload,
    fighter_channel_action_ids,
    torpedo_load_action_ids,
)

PRIORITY_POINT_DIAGNOSTIC_NOTE = (
    "Priority-point equality is not a hard solver constraint until production-queue "
    "semantics assign per-build priority_point_delta values."
)

FIGHTERS_STARBASE_TO_SHIP_ID = "fighters_starbase_to_ship"
FIGHTERS_SHIP_TO_STARBASE_ID = "fighters_ship_to_starbase"
FIGHTER_TRANSFER_DIRECTIONS_EXCLUSIVE_DIAGNOSTIC = (
    "at most one of fighters_starbase_to_ship and fighters_ship_to_starbase counts may be non-zero"
)


def _fighter_transfer_actions_both_present(
    aggregate_action_ids: frozenset[str],
) -> bool:
    return (
        FIGHTERS_STARBASE_TO_SHIP_ID in aggregate_action_ids
        and FIGHTERS_SHIP_TO_STARBASE_ID in aggregate_action_ids
    )


def _add_superclass_diversity_cap(
    model: cp_model.CpModel,
    action_count_vars: dict[str, cp_model.IntVar],
    member_action_ids: tuple[str, ...],
    *,
    cap: int,
    superclass: str,
) -> None:
    if len(member_action_ids) <= cap:
        return
    active_indicators = [
        add_count_active_indicator(
            model,
            action_count_vars[action_id],
            name=f"diversity_{superclass}_{action_id}_active",
        )
        for action_id in member_action_ids
    ]
    model.add(sum(active_indicators) <= cap)


def add_action_family_diversity_caps(
    model: cp_model.CpModel,
    action_count_vars: dict[str, cp_model.IntVar],
    aggregate_action_ids: frozenset[str],
    heuristics: InferenceRankingHeuristics,
) -> list[dict[str, object]]:
    """Apply torpedo-load and fighter-channel diversity caps; return diagnostics payload."""
    torpedo_ids = torpedo_load_action_ids(aggregate_action_ids)
    if torpedo_ids:
        _add_superclass_diversity_cap(
            model,
            action_count_vars,
            torpedo_ids,
            cap=heuristics.torpedo_load_diversity_cap,
            superclass="torpedo_loads",
        )
    fighter_ids = fighter_channel_action_ids(aggregate_action_ids)
    if fighter_ids:
        _add_superclass_diversity_cap(
            model,
            action_count_vars,
            fighter_ids,
            cap=heuristics.fighter_channel_diversity_cap,
            superclass="fighter_channel",
        )
    return diversity_caps_applied_payload(heuristics, aggregate_action_ids)


def _add_fighter_transfer_direction_exclusivity(
    model: cp_model.CpModel,
    action_count_vars: dict[str, cp_model.IntVar],
) -> None:
    """Forbid using both transfer directions in one explanation."""
    starbase_to_ship = action_count_vars[FIGHTERS_STARBASE_TO_SHIP_ID]
    ship_to_starbase = action_count_vars[FIGHTERS_SHIP_TO_STARBASE_ID]

    uses_starbase_to_ship = add_count_active_indicator(
        model,
        starbase_to_ship,
        name="fighter_transfer_starbase_to_ship_active",
    )
    uses_ship_to_starbase = add_count_active_indicator(
        model,
        ship_to_starbase,
        name="fighter_transfer_ship_to_starbase_active",
    )
    model.add(uses_starbase_to_ship + uses_ship_to_starbase <= 1)


@dataclass(frozen=True)
class _SumEqualityConstraint:
    diagnostic_label: str
    observation_attr: str
    coefficient_attr: str

    def applied_equality_string(self, observation: InferenceObservation) -> str:
        rhs = getattr(observation, self.observation_attr)
        return f"sum({self.diagnostic_label} * count) == {rhs}"

    def add_to_model(
        self,
        model: cp_model.CpModel,
        aggregate_actions: tuple[CandidateAction, ...],
        ship_build_combos: tuple[ShipBuildCombo, ...],
        action_count_vars: dict[str, cp_model.IntVar],
        combo_count_vars: dict[str, cp_model.IntVar],
        observation: InferenceObservation,
        *,
        military_score_alpha: int = 0,
    ) -> None:
        rhs = getattr(observation, self.observation_attr)
        lhs = sum(
            getattr(action, self.coefficient_attr) * action_count_vars[action.id]
            for action in aggregate_actions
        ) + sum(
            getattr(combo, self.coefficient_attr) * combo_count_vars[combo.combo_id]
            for combo in ship_build_combos
        )
        if self.coefficient_attr != "score_delta_2x":
            model.add(lhs == rhs)
            return
        partition_slack = observation.military_partition_slack_2x
        if partition_slack > 0:
            model.add(lhs >= rhs - partition_slack)
            model.add(lhs <= rhs + partition_slack)
            return
        if military_score_alpha > 0:
            model.add(lhs >= rhs - military_score_alpha)
            return
        model.add(lhs == rhs)


_MILITARY_SCORE_EQUALITY = _SumEqualityConstraint(
    "scoreDelta2x", "military_delta_2x", "score_delta_2x"
)
_WARSHIP_EQUALITY = _SumEqualityConstraint("warshipDelta", "warship_delta", "warship_delta")
_FREIGHTER_EQUALITY = _SumEqualityConstraint("freighterDelta", "freighter_delta", "freighter_delta")
_PRIORITY_POINT_EQUALITY = _SumEqualityConstraint(
    "priorityPointDelta", "priority_point_delta", "priority_point_delta"
)

_ALWAYS_ENFORCED_EQUALITIES = (
    _MILITARY_SCORE_EQUALITY,
    _WARSHIP_EQUALITY,
    _FREIGHTER_EQUALITY,
)


@dataclass(frozen=True)
class InferenceHardConstraints:
    """Which hard equalities and inequalities apply for one inference solve."""

    enforce_priority_point_constraint: bool = False
    military_score_alpha: int = 0

    @classmethod
    def from_problem(cls, problem: InferenceProblem) -> InferenceHardConstraints:
        return cls(
            enforce_priority_point_constraint=problem.enforce_priority_point_constraint,
            military_score_alpha=problem.military_score_alpha,
        )

    def enforced_equalities(self) -> tuple[_SumEqualityConstraint, ...]:
        if self.enforce_priority_point_constraint:
            return _ALWAYS_ENFORCED_EQUALITIES + (_PRIORITY_POINT_EQUALITY,)
        return _ALWAYS_ENFORCED_EQUALITIES

    def applied_equalities(
        self,
        observation: InferenceObservation,
        *,
        aggregate_action_ids: frozenset[str] | None = None,
    ) -> list[str]:
        strings: list[str] = []
        for constraint in self.enforced_equalities():
            if (
                constraint.coefficient_attr == "score_delta_2x"
                and observation.military_partition_slack_2x > 0
            ):
                slack = observation.military_partition_slack_2x
                strings.append(
                    f"{observation.military_delta_2x - slack} <= "
                    f"sum(scoreDelta2x * count) <= {observation.military_delta_2x + slack}"
                )
            elif constraint.coefficient_attr == "score_delta_2x" and self.military_score_alpha > 0:
                strings.append(
                    "sum(scoreDelta2x * count) >= "
                    f"{observation.military_delta_2x - self.military_score_alpha}"
                )
            else:
                strings.append(constraint.applied_equality_string(observation))
        strings.append(f"sum(buildSlotUsage * count) <= {observation.starbases_owned}")
        if aggregate_action_ids is not None and _fighter_transfer_actions_both_present(
            aggregate_action_ids
        ):
            strings.append(FIGHTER_TRANSFER_DIRECTIONS_EXCLUSIVE_DIAGNOSTIC)
        return strings

    def add_to_model(
        self,
        model: cp_model.CpModel,
        problem: InferenceProblem,
        action_count_vars: dict[str, cp_model.IntVar],
        combo_count_vars: dict[str, cp_model.IntVar],
    ) -> list[dict[str, object]]:
        observation = problem.observation
        for constraint in self.enforced_equalities():
            constraint.add_to_model(
                model,
                problem.aggregate_actions,
                problem.ship_build_combos,
                action_count_vars,
                combo_count_vars,
                observation,
                military_score_alpha=self.military_score_alpha,
            )
        model.add(
            sum(
                action.build_slot_usage * action_count_vars[action.id]
                for action in problem.aggregate_actions
            )
            + sum(
                combo.build_slot_usage * combo_count_vars[combo.combo_id]
                for combo in problem.ship_build_combos
            )
            <= observation.starbases_owned
        )
        aggregate_action_ids = frozenset(action.id for action in problem.aggregate_actions)
        if _fighter_transfer_actions_both_present(aggregate_action_ids):
            _add_fighter_transfer_direction_exclusivity(model, action_count_vars)
        return add_action_family_diversity_caps(
            model,
            action_count_vars,
            aggregate_action_ids,
            problem.ranking_heuristics,
        )


def solution_satisfies_exact_hard_equalities(
    solution: InferenceSolution,
    observation: InferenceObservation,
    catalog: ActionCatalog,
) -> bool:
    """Return whether a solution matches enforced hard equality targets."""
    actions_by_id = {action.id: action for action in catalog.aggregate_actions}
    combos_by_id = {combo.combo_id: combo for combo in catalog.ship_build_combos}
    military_sum = 0
    warship_sum = 0
    freighter_sum = 0
    for action in solution.actions:
        catalog_action = actions_by_id.get(action.action_id)
        if catalog_action is None:
            return False
        military_sum += catalog_action.score_delta_2x * action.count
        warship_sum += catalog_action.warship_delta * action.count
        freighter_sum += catalog_action.freighter_delta * action.count
    for ship_build in solution.ship_builds:
        combo = combos_by_id.get(ship_build.combo_id)
        if combo is None:
            return False
        military_sum += combo.score_delta_2x * ship_build.count
        warship_sum += combo.warship_delta * ship_build.count
        freighter_sum += combo.freighter_delta * ship_build.count
    return (
        abs(military_sum - observation.military_delta_2x) <= observation.military_partition_slack_2x
        and warship_sum == observation.warship_delta
        and freighter_sum == observation.freighter_delta
    )


def observation_to_constraints_payload(
    observation: InferenceObservation,
    *,
    hard_constraints: InferenceHardConstraints | None = None,
    aggregate_action_ids: frozenset[str] | None = None,
    diversity_caps_applied: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Serialize hard solver constraints for diagnostics."""
    constraints = hard_constraints or InferenceHardConstraints()
    payload: dict[str, object] = {
        "turn": observation.turn,
        "hostTurn": scoreboard_host_turn(observation.turn),
        "playerId": observation.player_id,
        "scoreboardDeltaSource": observation.scoreboard_delta_source,
        "militaryDelta2x": observation.military_delta_2x,
        "militaryPartitionSlack2x": observation.military_partition_slack_2x,
        "warshipDelta": observation.warship_delta,
        "freighterDelta": observation.freighter_delta,
        "requestedPriorityPointDelta": observation.priority_point_delta,
        "priorityPointConstraintEnforced": constraints.enforce_priority_point_constraint,
        "starbasesOwned": observation.starbases_owned,
        "isAfterShipLimit": observation.is_after_ship_limit,
        "militaryScoreAlpha": constraints.military_score_alpha,
        "appliedEqualities": constraints.applied_equalities(
            observation,
            aggregate_action_ids=aggregate_action_ids,
        ),
    }
    if not constraints.enforce_priority_point_constraint:
        payload["priorityPointConstraintNote"] = PRIORITY_POINT_DIAGNOSTIC_NOTE
    if diversity_caps_applied is not None:
        payload["diversityCapsApplied"] = diversity_caps_applied
    return payload

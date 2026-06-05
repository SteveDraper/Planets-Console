"""Hard CP-SAT constraints and matching diagnostics for military score build inference."""

from dataclasses import dataclass

from ortools.sat.python import cp_model

from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    ShipBuildCombo,
)

PRIORITY_POINT_DIAGNOSTIC_NOTE = (
    "Priority-point equality is not a hard solver constraint until production-queue "
    "semantics assign per-build priority_point_delta values."
)


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
    ) -> None:
        rhs = getattr(observation, self.observation_attr)
        model.add(
            sum(
                getattr(action, self.coefficient_attr) * action_count_vars[action.id]
                for action in aggregate_actions
            )
            + sum(
                getattr(combo, self.coefficient_attr) * combo_count_vars[combo.combo_id]
                for combo in ship_build_combos
            )
            == rhs
        )


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

    @classmethod
    def from_problem(cls, problem: InferenceProblem) -> InferenceHardConstraints:
        return cls(enforce_priority_point_constraint=problem.enforce_priority_point_constraint)

    def enforced_equalities(self) -> tuple[_SumEqualityConstraint, ...]:
        if self.enforce_priority_point_constraint:
            return _ALWAYS_ENFORCED_EQUALITIES + (_PRIORITY_POINT_EQUALITY,)
        return _ALWAYS_ENFORCED_EQUALITIES

    def applied_equalities(self, observation: InferenceObservation) -> list[str]:
        strings = [
            constraint.applied_equality_string(observation)
            for constraint in self.enforced_equalities()
        ]
        strings.append(f"sum(buildSlotUsage * count) <= {observation.starbases_owned}")
        return strings

    def add_to_model(
        self,
        model: cp_model.CpModel,
        problem: InferenceProblem,
        action_count_vars: dict[str, cp_model.IntVar],
        combo_count_vars: dict[str, cp_model.IntVar],
    ) -> None:
        observation = problem.observation
        for constraint in self.enforced_equalities():
            constraint.add_to_model(
                model,
                problem.aggregate_actions,
                problem.ship_build_combos,
                action_count_vars,
                combo_count_vars,
                observation,
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


def observation_to_constraints_payload(
    observation: InferenceObservation,
    *,
    hard_constraints: InferenceHardConstraints | None = None,
) -> dict[str, object]:
    """Serialize hard solver constraints for diagnostics."""
    constraints = hard_constraints or InferenceHardConstraints()
    payload: dict[str, object] = {
        "turn": observation.turn,
        "playerId": observation.player_id,
        "militaryDelta2x": observation.military_delta_2x,
        "warshipDelta": observation.warship_delta,
        "freighterDelta": observation.freighter_delta,
        "requestedPriorityPointDelta": observation.priority_point_delta,
        "priorityPointConstraintEnforced": constraints.enforce_priority_point_constraint,
        "starbasesOwned": observation.starbases_owned,
        "isAfterShipLimit": observation.is_after_ship_limit,
        "appliedEqualities": constraints.applied_equalities(observation),
    }
    if not constraints.enforce_priority_point_constraint:
        payload["priorityPointConstraintNote"] = PRIORITY_POINT_DIAGNOSTIC_NOTE
    return payload

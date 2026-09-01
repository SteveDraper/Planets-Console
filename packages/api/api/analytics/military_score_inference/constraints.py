"""Hard CP-SAT constraints and matching diagnostics for military score build inference."""

from dataclasses import dataclass

from ortools.sat.python import cp_model

from api.analytics.military_score_inference.accelerated_start import scoreboard_host_turn
from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.idle_dock_pp import (
    IDLE_DOCK_PP_EQUALITY_LABEL,
    idle_dock_implied_ships_built,
)
from api.analytics.military_score_inference.inference_objective import add_count_active_indicator
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    InferenceSolution,
    ShipBuildCombo,
    candidate_action_has_military_interval,
    candidate_military_subtotal_bounds_2x,
)
from api.analytics.military_score_inference.ranking_heuristics import (
    InferenceRankingHeuristics,
    diversity_caps_applied_payload,
    fighter_channel_action_ids,
    torpedo_load_action_ids,
)
from api.analytics.military_score_inference.ship_transfer_families import (
    ACQUIRED_SHIP_ACTION_PREFIX,
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
        if self.coefficient_attr == "score_delta_2x":
            lhs = _military_lhs(
                model,
                aggregate_actions,
                ship_build_combos,
                action_count_vars,
                combo_count_vars,
            )
            partition_slack = observation.military_partition_slack_2x
            if partition_slack > 0:
                model.add(lhs >= rhs - partition_slack)
                model.add(lhs <= rhs + partition_slack)
                return
            if military_score_alpha > 0:
                model.add(lhs >= rhs - military_score_alpha)
                return
            model.add(lhs == rhs)
            return
        lhs = sum(
            getattr(action, self.coefficient_attr) * action_count_vars[action.id]
            for action in aggregate_actions
        ) + sum(
            getattr(combo, self.coefficient_attr) * combo_count_vars[combo.combo_id]
            for combo in ship_build_combos
        )
        model.add(lhs == rhs)


def _military_lhs(
    model: cp_model.CpModel,
    aggregate_actions: tuple[CandidateAction, ...],
    ship_build_combos: tuple[ShipBuildCombo, ...],
    action_count_vars: dict[str, cp_model.IntVar],
    combo_count_vars: dict[str, cp_model.IntVar],
):
    terms: list[object] = []
    for action in aggregate_actions:
        count_var = action_count_vars[action.id]
        if candidate_action_has_military_interval(action):
            terms.append(_interval_military_contribution(model, action, count_var))
        else:
            terms.append(action.score_delta_2x * count_var)
    for combo in ship_build_combos:
        terms.append(combo.score_delta_2x * combo_count_vars[combo.combo_id])
    return sum(terms)


def _interval_military_contribution(
    model: cp_model.CpModel,
    action: CandidateAction,
    count_var: cp_model.IntVar,
):
    min_2x = action.score_delta_2x_min
    max_2x = action.score_delta_2x_max
    if min_2x is None or max_2x is None:
        return action.score_delta_2x * count_var
    lo = min(0, min_2x * action.upper_bound, max_2x * action.upper_bound)
    hi = max(0, min_2x * action.upper_bound, max_2x * action.upper_bound)
    contrib = model.new_int_var(lo, hi, f"{action.id}_military_contrib")
    model.add(contrib >= count_var * min_2x)
    model.add(contrib <= count_var * max_2x)
    return contrib


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
    enforce_idle_dock_pp_equality: bool = False
    military_score_alpha: int = 0

    @classmethod
    def from_problem(cls, problem: InferenceProblem) -> InferenceHardConstraints:
        return cls(
            enforce_priority_point_constraint=problem.enforce_priority_point_constraint,
            enforce_idle_dock_pp_equality=problem.enforce_idle_dock_pp_equality,
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
        if self.enforce_idle_dock_pp_equality:
            strings.append(IDLE_DOCK_PP_EQUALITY_LABEL)
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
        if self.enforce_idle_dock_pp_equality:
            ships_built = sum(
                combo.build_slot_usage * combo_count_vars[combo.combo_id]
                for combo in problem.ship_build_combos
            )
            implied_ships_built = idle_dock_implied_ships_built(observation)
            if implied_ships_built is not None:
                model.add(ships_built == implied_ships_built)
        _add_prior_fleet_departure_caps(model, problem, action_count_vars)
        _add_prior_fleet_group_departure_caps(model, problem, action_count_vars)
        _add_acquired_incoming_caps(model, problem, action_count_vars)
        aggregate_action_ids = frozenset(action.id for action in problem.aggregate_actions)
        if _fighter_transfer_actions_both_present(aggregate_action_ids):
            _add_fighter_transfer_direction_exclusivity(model, action_count_vars)
        return add_action_family_diversity_caps(
            model,
            action_count_vars,
            aggregate_action_ids,
            problem.ranking_heuristics,
        )


def _add_prior_fleet_departure_caps(
    model: cp_model.CpModel,
    problem: InferenceProblem,
    action_count_vars: dict[str, cp_model.IntVar],
) -> None:
    warship_usage = [
        action.prior_warship_usage * action_count_vars[action.id]
        for action in problem.aggregate_actions
        if action.prior_warship_usage
    ]
    if warship_usage:
        model.add(sum(warship_usage) <= problem.prior_warship_departure_cap)
    freighter_usage = [
        action.prior_freighter_usage * action_count_vars[action.id]
        for action in problem.aggregate_actions
        if action.prior_freighter_usage
    ]
    if freighter_usage:
        model.add(sum(freighter_usage) <= problem.prior_freighter_departure_cap)


def _add_prior_fleet_group_departure_caps(
    model: cp_model.CpModel,
    problem: InferenceProblem,
    action_count_vars: dict[str, cp_model.IntVar],
) -> None:
    """Share each departure group's record count across loss/gift/trade families.

    A group with no declared capacity caps at zero, so actions claiming a
    prior-fleet group can never exceed what the catalog carried for it.
    """
    usage_by_group: dict[str, list[object]] = {}
    for action in problem.aggregate_actions:
        if action.prior_group_key is None:
            continue
        usage = action.prior_warship_usage + action.prior_freighter_usage
        usage_by_group.setdefault(action.prior_group_key, []).append(
            usage * action_count_vars[action.id]
        )
    for group_key, usage_terms in usage_by_group.items():
        model.add(sum(usage_terms) <= problem.prior_departure_group_caps.get(group_key, 0))


def _add_acquired_incoming_caps(
    model: cp_model.CpModel,
    problem: InferenceProblem,
    action_count_vars: dict[str, cp_model.IntVar],
) -> None:
    """Cap total acquired ships at the paired incoming budget.

    Several counterparties are alternative signatures for the same arrival.
    A solution pairs with one matching donor; it does not consume every
    ``excess_out`` peer. Unknown class is exclusive alternatives, not two
    additive class columns.
    """
    _add_acquired_total_cap(model, problem, action_count_vars)
    _add_acquired_class_cap(
        model,
        problem,
        action_count_vars,
        cap=problem.acquired_warship_cap,
        warship=True,
    )
    _add_acquired_class_cap(
        model,
        problem,
        action_count_vars,
        cap=problem.acquired_freighter_cap,
        warship=False,
    )
    _add_exclusive_class_groups(model, problem, action_count_vars)


def _acquired_action_count_terms(
    problem: InferenceProblem,
    action_count_vars: dict[str, cp_model.IntVar],
    *,
    warship: bool | None,
) -> list[object]:
    terms: list[object] = []
    for action in problem.aggregate_actions:
        if not action.id.startswith(ACQUIRED_SHIP_ACTION_PREFIX):
            continue
        if warship is None:
            units = action.warship_delta + action.freighter_delta
        elif warship:
            units = action.warship_delta
        else:
            units = action.freighter_delta
        if units:
            terms.append(units * action_count_vars[action.id])
    return terms


def _add_acquired_total_cap(
    model: cp_model.CpModel,
    problem: InferenceProblem,
    action_count_vars: dict[str, cp_model.IntVar],
) -> None:
    cap = problem.acquired_ship_cap
    if not cap:
        return
    usage = _acquired_action_count_terms(problem, action_count_vars, warship=None)
    if usage:
        model.add(sum(usage) <= cap)


def _add_acquired_class_cap(
    model: cp_model.CpModel,
    problem: InferenceProblem,
    action_count_vars: dict[str, cp_model.IntVar],
    *,
    cap: int | None,
    warship: bool,
) -> None:
    if not cap:
        return
    usage = _acquired_action_count_terms(problem, action_count_vars, warship=warship)
    if usage:
        model.add(sum(usage) <= cap)


def _exclusive_group_hull_class(action: CandidateAction) -> str | None:
    """Warship or freighter when the action moves exactly one hull class."""
    has_warship = action.warship_delta != 0
    has_freighter = action.freighter_delta != 0
    if has_warship and not has_freighter:
        return "warship"
    if has_freighter and not has_warship:
        return "freighter"
    return None


def _add_class_active_indicator(
    model: cp_model.CpModel,
    action_count_vars: dict[str, cp_model.IntVar],
    action_ids: list[str],
    *,
    name: str,
) -> cp_model.IntVar:
    """True when any action in ``action_ids`` has count >= 1."""
    if len(action_ids) == 1:
        return add_count_active_indicator(
            model,
            action_count_vars[action_ids[0]],
            name=name,
        )
    active = model.new_bool_var(name)
    total = sum(action_count_vars[action_id] for action_id in action_ids)
    model.add(total >= 1).only_enforce_if(active)
    model.add(total == 0).only_enforce_if(active.negated())
    return active


def _add_exclusive_class_groups(
    model: cp_model.CpModel,
    problem: InferenceProblem,
    action_count_vars: dict[str, cp_model.IntVar],
) -> None:
    """Unknown-class transfers pick one hull class, not both.

    Several prior-fleet groups of the same class may all contribute. Exclusivity
    is class XOR within the group, not one-action-only.
    """
    ids_by_group_class: dict[str, dict[str, list[str]]] = {}
    for action in problem.aggregate_actions:
        if action.exclusive_class_group is None:
            continue
        hull_class = _exclusive_group_hull_class(action)
        if hull_class is None:
            continue
        ids_by_group_class.setdefault(action.exclusive_class_group, {}).setdefault(
            hull_class, []
        ).append(action.id)
    for group_key, ids_by_class in ids_by_group_class.items():
        if len(ids_by_class) < 2:
            continue
        class_active = [
            _add_class_active_indicator(
                model,
                action_count_vars,
                action_ids,
                name=f"exclusive_class_{group_key}_{hull_class}_active",
            )
            for hull_class, action_ids in ids_by_class.items()
        ]
        model.add(sum(class_active) <= 1)


def solution_satisfies_exact_hard_equalities(
    solution: InferenceSolution,
    observation: InferenceObservation,
    catalog: ActionCatalog,
) -> bool:
    """Return whether a solution matches enforced hard equality targets."""
    actions_by_id = {action.id: action for action in catalog.aggregate_actions}
    combos_by_id = {combo.combo_id: combo for combo in catalog.ship_build_combos}
    military_min = 0
    military_max = 0
    warship_sum = 0
    freighter_sum = 0
    for action in solution.actions:
        catalog_action = actions_by_id.get(action.action_id)
        if catalog_action is None:
            return False
        lo, hi = candidate_military_subtotal_bounds_2x(catalog_action, action.count)
        military_min += lo
        military_max += hi
        warship_sum += catalog_action.warship_delta * action.count
        freighter_sum += catalog_action.freighter_delta * action.count
    for ship_build in solution.ship_builds:
        combo = combos_by_id.get(ship_build.combo_id)
        if combo is None:
            return False
        military_min += combo.score_delta_2x * ship_build.count
        military_max += combo.score_delta_2x * ship_build.count
        warship_sum += combo.warship_delta * ship_build.count
        freighter_sum += combo.freighter_delta * ship_build.count
    slack = observation.military_partition_slack_2x
    return (
        military_min - slack <= observation.military_delta_2x <= military_max + slack
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
        "idleDockPpEqualityEnforced": constraints.enforce_idle_dock_pp_equality,
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

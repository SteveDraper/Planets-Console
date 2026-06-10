"""CP-SAT objective terms and active-count indicators for military score build inference."""

from ortools.sat.python import cp_model

from api.analytics.military_score_inference.models import (
    InferenceProblem,
    ProbabilityBucket,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.ranking_heuristics import (
    is_parsimony_eligible_slack_action,
    partial_weapon_slot_penalty_for_fit,
    ranking_penalty_from_marginal_weight,
)


def add_count_active_indicator(
    model: cp_model.CpModel,
    count_var: cp_model.IntVar,
    *,
    name: str,
) -> cp_model.IntVar:
    """Reify count_var >= 1 as a boolean indicator."""
    active = model.new_bool_var(name)
    model.add(count_var >= 1).only_enforce_if(active)
    model.add(count_var == 0).only_enforce_if(active.negated())
    return active


def max_aggregate_probability_weight(problem: InferenceProblem) -> int:
    if not problem.aggregate_actions:
        return 0
    return max(action.probability_weight for action in problem.aggregate_actions)


def max_combo_probability_weight(problem: InferenceProblem) -> int:
    if not problem.ship_build_combos:
        return 0
    return max(combo.probability_weight for combo in problem.ship_build_combos)


def _add_ranking_bin_indicators(
    model: cp_model.CpModel,
    count_var: cp_model.IntVar,
    buckets: tuple[ProbabilityBucket, ...],
    *,
    action_id: str,
    objective_terms: list[cp_model.LinearExpr],
) -> None:
    max_weight = max(bucket.marginal_weight for bucket in buckets)
    bin_indicators: list[cp_model.IntVar] = []
    has_positive_count = add_count_active_indicator(
        model,
        count_var,
        name=f"{action_id}_has_positive_count",
    )

    for index, bucket in enumerate(buckets):
        active = model.new_bool_var(f"{action_id}_ranking_bin_{index}")
        bin_indicators.append(active)
        lower_bound = 1 if bucket.lower_count == 0 else bucket.lower_count
        model.add(count_var >= lower_bound).only_enforce_if(active)
        model.add(count_var <= bucket.upper_count).only_enforce_if(active)
        penalty = ranking_penalty_from_marginal_weight(
            bucket.marginal_weight,
            max_marginal_weight=max_weight,
        )
        objective_terms.append(active * (-penalty))

    model.add(sum(bin_indicators) == has_positive_count)


def build_inference_objective_terms(
    model: cp_model.CpModel,
    problem: InferenceProblem,
    action_count_vars: dict[str, cp_model.IntVar],
    combo_count_vars: dict[str, cp_model.IntVar],
    *,
    ship_build_combos: tuple[ShipBuildCombo, ...],
) -> list[cp_model.LinearExpr]:
    """Assemble CP-SAT linear objective terms for one inference solve."""
    objective_terms: list[cp_model.LinearExpr] = []
    max_aggregate_weight = max_aggregate_probability_weight(problem)
    max_combo_weight = (
        max(combo.probability_weight for combo in ship_build_combos) if ship_build_combos else 0
    )

    for action in problem.aggregate_actions:
        count_var = action_count_vars[action.id]
        buckets = problem.probability_buckets_by_action_id.get(action.id)
        if buckets:
            _add_ranking_bin_indicators(
                model,
                count_var,
                buckets,
                action_id=action.id,
                objective_terms=objective_terms,
            )
            overflow_band = problem.tier_overflow_by_action_id.get(action.id)
            if overflow_band is not None:
                overflow_active = model.new_bool_var(f"{action.id}_tier_overflow_active")
                model.add(count_var > overflow_band.admission_cap).only_enforce_if(overflow_active)
                model.add(count_var <= overflow_band.admission_cap).only_enforce_if(
                    overflow_active.negated()
                )
                objective_terms.append(overflow_active * (-overflow_band.marginal_weight))
        else:
            active_action = add_count_active_indicator(
                model,
                count_var,
                name=f"{action.id}_active",
            )
            penalty = ranking_penalty_from_marginal_weight(
                action.probability_weight,
                max_marginal_weight=max_aggregate_weight,
            )
            objective_terms.append(active_action * (-penalty))

    for combo in ship_build_combos:
        combo_penalty = ranking_penalty_from_marginal_weight(
            combo.probability_weight,
            max_marginal_weight=max_combo_weight,
        )
        partial_slot_penalty = partial_weapon_slot_penalty_for_fit(
            beam_count=combo.beam_count,
            launcher_count=combo.launcher_count,
            hull_beam_slots=combo.hull_beam_slots,
            hull_launcher_slots=combo.hull_launcher_slots,
            heuristics=problem.ranking_heuristics,
        )
        objective_terms.append(
            combo_count_vars[combo.combo_id] * (-combo_penalty + partial_slot_penalty)
        )

    for action in problem.aggregate_actions:
        if not is_parsimony_eligible_slack_action(action.id):
            continue
        active_slack_type = add_count_active_indicator(
            model,
            action_count_vars[action.id],
            name=f"parsimony_active_{action.id}",
        )
        objective_terms.append(
            active_slack_type * problem.ranking_heuristics.parsimony_per_active_slack_type
        )

    return objective_terms

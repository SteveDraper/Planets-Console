"""Label expansion ranks each ship class, then sums only the top labelings."""

from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.solver import (
    _expand_score_equivalent_solutions,
    merge_score_equivalent_combos,
    solution_rank_objective,
)


def _observation() -> InferenceObservation:
    return InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=1000,
        warship_delta=2,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=2,
        is_after_ship_limit=False,
    )


def _combo(
    combo_id: str,
    *,
    hull_id: int,
    score_delta_2x: int,
    probability_weight: int,
    beam_count: int = 0,
    hull_beam_slots: int = 0,
) -> ShipBuildCombo:
    return ShipBuildCombo(
        combo_id=combo_id,
        hull_id=hull_id,
        engine_id=1,
        beam_id=1 if beam_count else None,
        torp_id=None,
        beam_count=beam_count,
        launcher_count=0,
        labels=(combo_id,),
        score_delta_2x=score_delta_2x,
        warship_delta=1,
        upper_bound=1,
        probability_weight=probability_weight,
        hull_beam_slots=hull_beam_slots,
        hull_launcher_slots=0,
    )


def _combo_ids(solution) -> frozenset[str]:
    return frozenset(build.combo_id for build in solution.ship_builds)


def test_partial_slot_penalty_outranks_a_higher_prior_in_the_best_pair() -> None:
    """A full fit with a slightly worse prior beats a partial fit of the same class."""
    partial_high = _combo(
        "partial_high",
        hull_id=1,
        score_delta_2x=400,
        probability_weight=100,
        beam_count=1,
        hull_beam_slots=4,
    )
    full_mid = _combo(
        "full_mid",
        hull_id=2,
        score_delta_2x=400,
        probability_weight=80,
        beam_count=4,
        hull_beam_slots=4,
    )
    full_low = _combo(
        "full_low",
        hull_id=3,
        score_delta_2x=400,
        probability_weight=10,
        beam_count=4,
        hull_beam_slots=4,
    )
    best_partner = _combo("best_partner", hull_id=4, score_delta_2x=600, probability_weight=100)
    mid_partner = _combo("mid_partner", hull_id=5, score_delta_2x=600, probability_weight=90)
    low_partner = _combo("low_partner", hull_id=6, score_delta_2x=600, probability_weight=40)
    problem = InferenceProblem(
        observation=_observation(),
        aggregate_actions=(),
        ship_build_combos=(
            partial_high,
            full_mid,
            full_low,
            best_partner,
            mid_partner,
            low_partner,
        ),
        max_solutions=2,
    )
    merged = merge_score_equivalent_combos(problem.ship_build_combos)
    combo_counts = dict.fromkeys(merged.members_by_merged_id, 1)
    solutions = _expand_score_equivalent_solutions(
        problem,
        {},
        combo_counts,
        merged,
        max_expansions=2,
    )

    assert [_combo_ids(solution) for solution in solutions] == [
        frozenset({"full_mid", "best_partner"}),
        frozenset({"partial_high", "best_partner"}),
    ]
    assert all(
        solution.objective_value == solution_rank_objective(problem, solution)
        for solution in solutions
    )
    assert solutions[0].objective_value > solutions[1].objective_value


def test_top_k_labelings_omit_fittings_outside_each_class_prefix() -> None:
    classes = []
    for score_delta_2x, prefix in ((400, "a"), (600, "b"), (800, "c")):
        for index in range(8):
            classes.append(
                _combo(
                    f"{prefix}{index}",
                    hull_id=score_delta_2x + index,
                    score_delta_2x=score_delta_2x,
                    probability_weight=100 - (10 * index),
                )
            )
    problem = InferenceProblem(
        observation=_observation(),
        aggregate_actions=(),
        ship_build_combos=tuple(classes),
        max_solutions=3,
    )
    merged = merge_score_equivalent_combos(problem.ship_build_combos)
    combo_counts = dict.fromkeys(merged.members_by_merged_id, 1)
    solutions = _expand_score_equivalent_solutions(
        problem,
        {},
        combo_counts,
        merged,
        max_expansions=3,
    )

    assert len(solutions) == 3
    assert _combo_ids(solutions[0]) == frozenset({"a0", "b0", "c0"})
    held_ids = {combo_id for solution in solutions for combo_id in _combo_ids(solution)}
    assert held_ids.isdisjoint({"a4", "b4", "c4", "a7", "b7", "c7"})
    assert all(
        solution.objective_value == solution_rank_objective(problem, solution)
        for solution in solutions
    )

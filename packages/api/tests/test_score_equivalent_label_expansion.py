"""Label expansion ranks each ship class, then sums only the top labelings."""

from api.analytics.military_score_inference import solver
from api.analytics.military_score_inference.catalog_model import merge_score_equivalent_combos
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.solver import (
    _expand_score_equivalent_solutions,
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
        max_labelings=2,
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
        max_labelings=3,
    )

    assert len(solutions) == 3
    assert _combo_ids(solutions[0]) == frozenset({"a0", "b0", "c0"})
    held_ids = {combo_id for solution in solutions for combo_id in _combo_ids(solution)}
    assert held_ids.isdisjoint({"a4", "b4", "c4", "a7", "b7", "c7"})
    assert all(
        solution.objective_value == solution_rank_objective(problem, solution)
        for solution in solutions
    )


def test_top_k_expansion_scores_each_fitting_and_keeps_only_k_solutions(monkeypatch) -> None:
    """Rank each score class on its own and build K labelings, not their product.

    Three merged classes hold 155, 46, and 30 fittings. Expansion scores each
    fitting once, returns 20 solutions in descending objective order, and the
    first solution is the best fitting of every class.
    """
    class_sizes = (155, 46, 30)
    top_k = 20
    weight_base = 50_000_000
    weight_strides = (1, 1_000, 1_000_000)
    score_deltas = (400, 600, 800)
    fittings = []
    best_combo_ids = []
    for class_index, class_size in enumerate(class_sizes):
        best_combo_ids.append(f"c{class_index}-0")
        for member_index in range(class_size):
            fittings.append(
                _combo(
                    f"c{class_index}-{member_index}",
                    hull_id=class_index * 10_000 + member_index,
                    score_delta_2x=score_deltas[class_index],
                    probability_weight=weight_base - member_index * weight_strides[class_index],
                )
            )
    problem = InferenceProblem(
        observation=_observation(),
        aggregate_actions=(),
        ship_build_combos=tuple(fittings),
        max_solutions=top_k,
    )
    merged = merge_score_equivalent_combos(problem.ship_build_combos)
    assert sorted(len(members) for members in merged.members_by_merged_id.values()) == sorted(
        class_sizes
    )
    combo_counts = dict.fromkeys(merged.members_by_merged_id, 1)

    scoring_calls = 0
    solutions_materialized = 0
    original_coefficient = solver.ship_build_objective_coefficient
    original_solution = solver.InferenceSolution

    def _counting_coefficient(*args, **kwargs):
        nonlocal scoring_calls
        scoring_calls += 1
        return original_coefficient(*args, **kwargs)

    def _counting_solution(*args, **kwargs):
        nonlocal solutions_materialized
        solutions_materialized += 1
        return original_solution(*args, **kwargs)

    monkeypatch.setattr(solver, "ship_build_objective_coefficient", _counting_coefficient)
    monkeypatch.setattr(solver, "InferenceSolution", _counting_solution)
    solutions = _expand_score_equivalent_solutions(
        problem,
        {},
        combo_counts,
        merged,
        max_labelings=top_k,
    )
    member_count = sum(class_sizes)
    cross_product = class_sizes[0] * class_sizes[1] * class_sizes[2]
    assert scoring_calls == member_count
    assert scoring_calls * 100 < cross_product
    assert solutions_materialized <= top_k
    assert len(solutions) == top_k
    assert _combo_ids(solutions[0]) == frozenset(best_combo_ids)
    assert all(
        solutions[index].objective_value > solutions[index + 1].objective_value
        for index in range(top_k - 1)
    )
    assert all(
        solution.objective_value == solution_rank_objective(problem, solution)
        for solution in solutions
    )


def _emitted_combo_ids(solutions) -> list[tuple[str, ...]]:
    return [tuple(build.combo_id for build in solution.ship_builds) for solution in solutions]


def test_equal_sum_labelings_emit_in_ascending_index_tuple_order() -> None:
    """Tied sums emit in ascending index-tuple order.

    Class A (score 400) then class B (score 600) are the combo_counts axes.
    Equal probability weights on A sort by combo id, so that axis is c, a, b
    and B is y, x, w. The three equal sums are index tuples (0, 2), (1, 0),
    and (2, 0): (c, w), (a, y), (b, y). A second expansion returns the same
    order.
    """
    class_a = (
        _combo("b", hull_id=1, score_delta_2x=400, probability_weight=50),
        _combo("c", hull_id=2, score_delta_2x=400, probability_weight=100),
        _combo("a", hull_id=3, score_delta_2x=400, probability_weight=50),
    )
    class_b = (
        _combo("w", hull_id=4, score_delta_2x=600, probability_weight=50),
        _combo("y", hull_id=5, score_delta_2x=600, probability_weight=100),
        _combo("x", hull_id=6, score_delta_2x=600, probability_weight=80),
    )
    problem = InferenceProblem(
        observation=_observation(),
        aggregate_actions=(),
        ship_build_combos=class_a + class_b,
        max_solutions=5,
    )
    merged = merge_score_equivalent_combos(problem.ship_build_combos)
    combo_counts = dict.fromkeys(merged.members_by_merged_id, 1)
    expected = [
        ("c", "y"),
        ("c", "x"),
        ("c", "w"),
        ("a", "y"),
        ("b", "y"),
    ]

    def expand_labelings():
        return _expand_score_equivalent_solutions(
            problem,
            {},
            combo_counts,
            merged,
            max_labelings=5,
        )

    solutions = expand_labelings()
    repeat = expand_labelings()
    tied = solutions[2:]

    assert _emitted_combo_ids(solutions) == expected
    assert _emitted_combo_ids(repeat) == expected
    assert solutions[0].objective_value > solutions[1].objective_value > tied[0].objective_value
    assert len({solution.objective_value for solution in tied}) == 1
    assert all(
        solution.objective_value == solution_rank_objective(problem, solution)
        for solution in solutions
    )

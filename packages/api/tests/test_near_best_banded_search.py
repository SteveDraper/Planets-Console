"""Band enumeration and single-hit seeds match the successive near-best walk."""

from api.analytics.military_score_inference.actions import (
    ActionCatalog,
    build_inference_problem,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceSolution,
    InferenceSolutionShipBuild,
    ShipBuildCombo,
    WallSolveClip,
)
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    _solve_catalog,
    _solve_seed_progression,
)
from api.analytics.military_score_inference.ranked_solution_buffer import (
    SolutionSignature,
    admit_ranked_solution,
    solution_signature,
)
from api.analytics.military_score_inference.solver import solve_inference_problem


def _combo(combo_id: str, *, hull_id: int, score_delta_2x: int) -> ShipBuildCombo:
    return ShipBuildCombo(
        combo_id=combo_id,
        hull_id=hull_id,
        engine_id=1,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
        labels=(combo_id,),
        score_delta_2x=score_delta_2x,
        warship_delta=1,
        upper_bound=1,
        probability_weight=100,
    )


def _observation() -> InferenceObservation:
    return InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=1000,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=2,
        is_after_ship_limit=False,
    )


def _catalog() -> ActionCatalog:
    """One full-score ship, plus a partial ship completed by two equal-score loads."""
    return ActionCatalog(
        aggregate_actions=(
            CandidateAction(id="load_a", label="Load A", score_delta_2x=100, upper_bound=4),
            CandidateAction(id="load_b", label="Load B", score_delta_2x=100, upper_bound=4),
        ),
        ship_build_combos=(
            _combo("full", hull_id=1, score_delta_2x=1000),
            _combo("partial", hull_id=2, score_delta_2x=600),
        ),
        probability_buckets_by_action_id={},
    )


def _ranked(
    solutions: list[InferenceSolution] | tuple[InferenceSolution, ...],
) -> frozenset[tuple[int, SolutionSignature]]:
    return frozenset(
        (solution.objective_value, solution_signature(solution)) for solution in solutions
    )


def _pipeline(*, successive_search: bool) -> tuple[list[InferenceSolution], int]:
    observation = _observation()
    catalog = _catalog()
    held: list[InferenceSolution] = []
    seen: set[SolutionSignature] = set()

    def admit(solution: InferenceSolution) -> None:
        admit_ranked_solution(held, seen, solution, max_solutions=20)

    seed = InferenceSolution(
        objective_value=0,
        actions=(),
        ship_builds=(InferenceSolutionShipBuild(combo_id="partial", label="partial", count=1),),
    )
    seed_result, _seed_problem = _solve_seed_progression(
        observation,
        catalog,
        seed,
        max_solutions=20,
        next_solve_clip=lambda: WallSolveClip(max_time_in_seconds=5.0),
        on_solution=admit,
        successive_structural_search=successive_search,
    )
    assert seed_result is not None
    _solve_catalog(
        observation,
        catalog,
        max_solutions=20,
        solve_clip=WallSolveClip(max_time_in_seconds=5.0),
        on_solution=admit,
        successive_structural_search=successive_search,
    )
    return held, int(seed_result.diagnostics["structural_hit_count"])


def test_seed_first_hit_and_band_enumeration_match_successive_results() -> None:
    """Optimized seed and free search keep the same admitted explanations.

    The successive walk re-solves after every no-good. The optimized path stops
    a seed at its first structural hit and enumerates the free-search band once.
    """
    problem = build_inference_problem(_observation(), _catalog(), max_solutions=20)
    successive = solve_inference_problem(problem, successive_structural_search=True)
    enumerated = solve_inference_problem(problem)
    assert int(successive.diagnostics["structural_hit_count"]) > 1
    assert _ranked(enumerated.solutions) == _ranked(successive.solutions)
    assert (
        enumerated.diagnostics["structural_hit_count"]
        == successive.diagnostics["structural_hit_count"]
    )
    assert enumerated.diagnostics["stopped_reason"] == successive.diagnostics["stopped_reason"]

    baseline_held, baseline_seed_hits = _pipeline(successive_search=True)
    optimized_held, optimized_seed_hits = _pipeline(successive_search=False)
    assert baseline_seed_hits > 1
    assert optimized_seed_hits == 1
    assert _ranked(optimized_held) == _ranked(baseline_held)

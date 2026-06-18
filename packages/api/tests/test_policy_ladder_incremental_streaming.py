"""Tests for within-tier incremental merge admission during policy ladder steps."""

from __future__ import annotations

from api.analytics.military_score_inference.models import InferenceSolution
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    run_policy_ladder_tier_step,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies


def test_run_policy_ladder_tier_step_calls_on_admitted_for_each_within_tier_solution(
    sample_turn,
    monkeypatch,
) -> None:
    policy_steps = tuple(resolve_tier_policies(None))
    state = PolicyLadderState(policy_steps=policy_steps)

    from api.analytics.military_score_inference.analytic import build_inference_observation

    score = sample_turn.scores[0]
    observation = build_inference_observation(score, sample_turn)

    from api.analytics.military_score_inference.models import InferenceSolutionAction

    solution_one = InferenceSolution(
        objective_value=20,
        actions=(InferenceSolutionAction(action_id="action_a", label="Action A", count=1),),
    )
    solution_two = InferenceSolution(
        objective_value=10,
        actions=(InferenceSolutionAction(action_id="action_b", label="Action B", count=1),),
    )

    def fake_solve_catalog(
        _observation,
        _catalog,
        *,
        race_id=None,
        max_solutions,
        time_limit_seconds,
        military_score_alpha=0,
        fixed_combo_counts=None,
        combo_count_neighborhood=0,
        cancel_token=None,
        on_solution=None,
    ):
        del race_id, max_solutions, time_limit_seconds, military_score_alpha
        del fixed_combo_counts, combo_count_neighborhood, cancel_token
        if on_solution is not None:
            on_solution(solution_one)
            on_solution(solution_two)
        from api.analytics.military_score_inference.actions import build_inference_problem

        problem = build_inference_problem(_observation, _catalog, max_solutions=2)
        from api.analytics.military_score_inference.models import InferenceResult

        return (
            InferenceResult(
                status=STATUS_EXACT,
                solutions=(solution_one, solution_two),
                diagnostics={},
            ),
            problem,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step._solve_seed_progression",
        lambda *args, **kwargs: (None, None),
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step._solve_catalog",
        fake_solve_catalog,
    )

    admitted: list[InferenceSolution] = []
    run_policy_ladder_tier_step(
        state,
        observation,
        sample_turn,
        time_limit_seconds=None,
        on_admitted=admitted.append,
    )

    assert [solution.objective_value for solution in admitted] == [20, 10]
    assert len(state.merged_solutions) == 2

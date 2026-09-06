"""Ship-first overshoot overlay and residual persist (#413 / design §3.10)."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.hopeless_classifier import (
    EXPENSIVE_TIER_STEP_IDS,
    HopelessRowFacts,
)
from api.analytics.military_score_inference.inference_api_payload import (
    inference_result_to_api_payload,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
    InferenceSolutionAction,
)
from api.analytics.military_score_inference.policy_ladder import solve_with_policy_ladder
from api.analytics.military_score_inference.policy_ladder_admission import (
    leftover_0_solutions,
    maybe_ship_first_prefix_stop_after_step,
    solution_is_leftover_0_exact,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.ranked_solution_buffer import solution_signature
from api.analytics.military_score_inference.ship_first_overshoot import (
    PLANET_OR_STARBASE_POST_STEP_IDS,
    SHIP_FIRST_PREFIX_LAST_STEP_ID,
    SHIP_FIRST_PREFIX_STOP_REASON,
    ShipFirstOvershootPlan,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_MINE_SCORE_RESIDUAL,
    STATUS_MODERATE_RESIDUAL,
    STATUS_NO_EXACT_SOLUTION,
)
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.analytics.military_score_inference.worthwhile_remainder_bound import (
    WorthwhileRemainderBound,
)
from api.models.space import Minefield
from api.serialization.inference_row_persistence import persisted_inference_row_from_wire_complete

from tests.fixtures.military_score_inference import _observation, without_player_minefields

_VIEWPOINT_PLAYER_ID = 8


def _facts(**overrides: object) -> HopelessRowFacts:
    values: dict[str, object] = {
        "planet_delta": 0,
        "starbase_delta": 0,
        "sticky_prior": False,
        "max_owner_minefield_units": 0,
    }
    values.update(overrides)
    return HopelessRowFacts(**values)


def _minefield(*, units: int) -> Minefield:
    return Minefield(
        id=1,
        ownerid=_VIEWPOINT_PLAYER_ID,
        isweb=False,
        ishidden=False,
        units=units,
        infoturn=111,
        friendlycode="???",
        x=0,
        y=0,
        radius=1,
    )


def _open_bound(*, cap_2x: int, slack_2x: int = 1) -> WorthwhileRemainderBound:
    return WorthwhileRemainderBound(
        bound_2x=float(cap_2x),
        cap_2x=cap_2x,
        overshoot_window_empty=cap_2x <= slack_2x,
        empirical_leftover_2x=float(cap_2x),
        mixed_leftover_2x=float(cap_2x),
        interpolant_leftover_2x=float(cap_2x),
        observed_floor_2x=0.0,
        n_total=1,
        mixture_weight=1.0,
        p90_total_units=100,
        p90_field_count=1,
    )


def _emit_mock_solver_solutions(result: InferenceResult, **kwargs) -> InferenceResult:
    on_solution = kwargs.get("on_solution")
    if on_solution is not None:
        for solution in result.solutions:
            on_solution(solution)
    return result


def _overshoot_solution(*, objective: int = -10) -> InferenceSolution:
    return InferenceSolution(
        objective_value=objective,
        actions=(InferenceSolutionAction(action_id="build_rush", label="Build", count=1),),
        ship_builds=(),
    )


def test_skip_leftover_0_when_current_turn_owner_fields(sample_turn, monkeypatch) -> None:
    exact = InferenceResult(status=STATUS_EXACT, solutions=(_overshoot_solution(),), diagnostics={})
    overshoot = InferenceResult(
        status=STATUS_EXACT,
        solutions=(_overshoot_solution(objective=-20),),
        diagnostics={},
    )
    modes: list[str] = []

    def _solve_side_effect(problem, **kwargs):
        if problem.military_overshoot_cap_2x is not None:
            modes.append("overshoot")
            return _emit_mock_solver_solutions(overshoot, **kwargs)
        modes.append("exact")
        return _emit_mock_solver_solutions(exact, **kwargs)

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.ship_first_overshoot.worthwhile_remainder_bound_for_turn",
        lambda *_args, **_kwargs: _open_bound(cap_2x=40),
    )
    turn = replace(sample_turn, minefields=(_minefield(units=50),))
    observation = _observation(
        military_delta_2x=400, warship_delta=1, military_partition_slack_2x=1
    )
    result, _, _, attempted, _ = solve_with_policy_ladder(
        observation,
        turn,
        hopeless_context=_facts(max_owner_minefield_units=50),
        time_limit_seconds=60.0,
    )
    assert "exact" not in modes
    assert "overshoot" in modes
    assert result.status == STATUS_MINE_SCORE_RESIDUAL
    assert result.solutions
    assert PLANET_OR_STARBASE_POST_STEP_IDS.isdisjoint(attempted)
    assert EXPENSIVE_TIER_STEP_IDS.isdisjoint(attempted)
    assert "admit_ship_torpedoes" in attempted


def test_exact_preempts_overshoot_without_current_turn_owner_fields(
    sample_turn, monkeypatch
) -> None:
    exact = InferenceResult(status=STATUS_EXACT, solutions=(_overshoot_solution(),), diagnostics={})
    modes: list[str] = []

    def _solve_side_effect(problem, **kwargs):
        if problem.military_overshoot_cap_2x is not None:
            modes.append("overshoot")
            return _emit_mock_solver_solutions(
                InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
                **kwargs,
            )
        modes.append("exact")
        return _emit_mock_solver_solutions(exact, **kwargs)

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_admission."
        "solution_satisfies_exact_hard_equalities",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.ship_first_overshoot.worthwhile_remainder_bound_for_turn",
        lambda *_args, **_kwargs: _open_bound(cap_2x=40),
    )
    turn = without_player_minefields(sample_turn, _VIEWPOINT_PLAYER_ID)
    observation = _observation(military_delta_2x=400, warship_delta=1)
    result, _, _, attempted, _ = solve_with_policy_ladder(
        observation,
        turn,
        hopeless_context=_facts(sticky_prior=True),
        time_limit_seconds=60.0,
    )
    assert "exact" in modes
    assert "overshoot" not in modes
    assert result.status == STATUS_EXACT
    assert PLANET_OR_STARBASE_POST_STEP_IDS.isdisjoint(attempted)


def test_overshoot_after_exact_unsat_uses_phase_two_cap(sample_turn, monkeypatch) -> None:
    caps: list[int | None] = []

    def _solve_side_effect(problem, **kwargs):
        caps.append(problem.military_overshoot_cap_2x)
        if problem.military_overshoot_cap_2x is not None:
            return _emit_mock_solver_solutions(
                InferenceResult(
                    status=STATUS_EXACT,
                    solutions=(_overshoot_solution(),),
                    diagnostics={},
                ),
                **kwargs,
            )
        return _emit_mock_solver_solutions(
            InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.ship_first_overshoot.worthwhile_remainder_bound_for_turn",
        lambda *_args, **_kwargs: _open_bound(cap_2x=37),
    )
    turn = without_player_minefields(sample_turn, _VIEWPOINT_PLAYER_ID)
    observation = _observation(
        military_delta_2x=400,
        warship_delta=1,
        military_partition_slack_2x=1,
    )
    result, _, _, attempted, _ = solve_with_policy_ladder(
        observation,
        turn,
        hopeless_context=_facts(sticky_prior=True),
        time_limit_seconds=60.0,
    )
    assert 37 in caps
    assert result.status == STATUS_MINE_SCORE_RESIDUAL
    assert result.solutions
    assert PLANET_OR_STARBASE_POST_STEP_IDS.isdisjoint(attempted)


def test_empty_overshoot_window_is_empty_list_residual(sample_turn, monkeypatch) -> None:
    modes: list[str] = []

    def _solve_side_effect(problem, **kwargs):
        modes.append("overshoot" if problem.military_overshoot_cap_2x is not None else "exact")
        return _emit_mock_solver_solutions(
            InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.ship_first_overshoot.worthwhile_remainder_bound_for_turn",
        lambda *_args, **_kwargs: _open_bound(cap_2x=1, slack_2x=1),
    )
    turn = replace(sample_turn, minefields=(_minefield(units=20),))
    observation = _observation(
        military_delta_2x=-40, warship_delta=0, military_partition_slack_2x=1
    )
    result, catalog, problem, attempted, _ = solve_with_policy_ladder(
        observation,
        turn,
        hopeless_context=_facts(max_owner_minefield_units=20),
        time_limit_seconds=60.0,
    )
    assert "overshoot" not in modes
    assert result.status == STATUS_MINE_SCORE_RESIDUAL
    assert result.solutions == ()
    assert PLANET_OR_STARBASE_POST_STEP_IDS.isdisjoint(attempted)
    payload = inference_result_to_api_payload(
        result,
        catalog,
        observation,
        turn,
        problem,
    )
    assert payload["solutions"] == []
    assert payload["placeholders"] == []
    assert payload["unexplainedMilitaryDelta2x"] == observation.military_delta_2x


def test_moderate_residual_still_has_no_solution_list(sample_turn, monkeypatch) -> None:
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        lambda _problem, **kwargs: _emit_mock_solver_solutions(
            InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
            **kwargs,
        ),
    )
    turn = without_player_minefields(sample_turn, _VIEWPOINT_PLAYER_ID)
    observation = _observation(military_delta_2x=-10, warship_delta=0)
    result, catalog, problem, attempted, _ = solve_with_policy_ladder(
        observation,
        turn,
        hopeless_context=_facts(),
        time_limit_seconds=60.0,
    )
    assert result.status == STATUS_MODERATE_RESIDUAL
    assert result.solutions == ()
    assert "full_components" in attempted
    payload = inference_result_to_api_payload(result, catalog, observation, turn, problem)
    assert payload["solutions"] == []
    assert payload["placeholders"] == []


def test_mine_score_residual_persists_ranked_solutions_and_rank1_leftover(sample_turn) -> None:
    observation = _observation(
        military_delta_2x=400, warship_delta=1, military_partition_slack_2x=1
    )
    action = CandidateAction(
        id="build_rush",
        label="Build Rush",
        score_delta_2x=420,
        warship_delta=1,
        upper_bound=1,
    )
    catalog = ActionCatalog(
        aggregate_actions=(action,),
        ship_build_combos=(),
        probability_buckets_by_action_id={},
    )
    solution = _overshoot_solution()
    result = InferenceResult(
        status=STATUS_MINE_SCORE_RESIDUAL,
        solutions=(solution,),
        diagnostics={},
    )
    problem = InferenceProblem(observation=observation, aggregate_actions=(action,))
    payload = inference_result_to_api_payload(result, catalog, observation, sample_turn, problem)
    assert payload["status"] == STATUS_MINE_SCORE_RESIDUAL
    assert payload["solutionCount"] == 1
    assert payload["placeholders"] == []
    assert payload["unexplainedMilitaryDelta2x"] == 20
    row = persisted_inference_row_from_wire_complete(
        {"type": "complete", **{k: v for k, v in payload.items() if k != "diagnostics"}}
    )
    assert row.status == STATUS_MINE_SCORE_RESIDUAL
    assert row.solutions
    assert row.placeholders == []
    assert row.unexplained_military_delta_2x == 20


def _interval_mix_actions() -> tuple[CandidateAction, CandidateAction]:
    ship = CandidateAction(
        id="build_rush",
        label="Build Rush",
        score_delta_2x=420,
        warship_delta=1,
        upper_bound=1,
    )
    decrease = CandidateAction(
        id="loss:warship:envelope",
        label="Ship loss",
        score_delta_2x=0,
        warship_delta=0,
        score_delta_2x_min=-200,
        score_delta_2x_max=0,
        upper_bound=1,
    )
    return ship, decrease


def _interval_mix_solution() -> InferenceSolution:
    ship, decrease = _interval_mix_actions()
    return InferenceSolution(
        objective_value=-10,
        actions=(
            InferenceSolutionAction(action_id=ship.id, label=ship.label, count=1),
            InferenceSolutionAction(action_id=decrease.id, label=decrease.label, count=1),
        ),
        ship_builds=(),
    )


def _interval_mix_catalog(*, policy_step_id: str = "", policy_step_index: int = 0) -> ActionCatalog:
    ship, decrease = _interval_mix_actions()
    return ActionCatalog(
        aggregate_actions=(ship, decrease),
        ship_build_combos=(),
        probability_buckets_by_action_id={},
        policy_step_id=policy_step_id,
        policy_step_index=policy_step_index,
    )


def test_overshoot_admit_is_not_leftover_0_via_envelope_coverage() -> None:
    observation = _observation(
        military_delta_2x=400, warship_delta=1, military_partition_slack_2x=1
    )
    catalog = _interval_mix_catalog()
    solution = _interval_mix_solution()
    assert solution_is_leftover_0_exact(solution, observation, catalog) is True
    assert (
        solution_is_leftover_0_exact(solution, observation, catalog, admitted_under_overshoot=True)
        is False
    )
    kept = leftover_0_solutions(
        [solution],
        observation,
        catalog,
        overshoot_signatures={solution_signature(solution)},
    )
    assert kept == []


def test_prefix_stop_only_marks_ladder_complete() -> None:
    step = next(
        policy_step
        for policy_step in resolve_tier_policies()
        if policy_step.id == SHIP_FIRST_PREFIX_LAST_STEP_ID
    )
    state = PolicyLadderState(
        policy_steps=(step,),
        ship_first_overshoot=ShipFirstOvershootPlan(
            active=True,
            skip_leftover_0_exact=True,
            cap_2x=40,
            overshoot_window_empty=False,
        ),
        last_status=STATUS_NO_EXACT_SOLUTION,
    )
    assert maybe_ship_first_prefix_stop_after_step(state, policy_step=step) is True
    assert state.ladder_complete is True
    assert state.ladder_early_stop_reason == SHIP_FIRST_PREFIX_STOP_REASON
    assert state.last_status == STATUS_NO_EXACT_SOLUTION


def test_skip_leftover_0_interval_mix_persists_residual_not_empty_exact(
    sample_turn, monkeypatch
) -> None:
    solution = _interval_mix_solution()
    overshoot_steps: list[str] = []

    def _catalog_from_turn(_observation, _turn, **kwargs):
        policy_step = kwargs.get("policy_step")
        return _interval_mix_catalog(
            policy_step_id=policy_step.id if policy_step is not None else "",
            policy_step_index=kwargs.get("policy_step_index", 0),
        )

    def _solve_side_effect(problem, **kwargs):
        if problem.military_overshoot_cap_2x is None:
            return _emit_mock_solver_solutions(
                InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
                **kwargs,
            )
        overshoot_steps.append(problem.policy_step_id)
        return _emit_mock_solver_solutions(
            InferenceResult(status=STATUS_EXACT, solutions=(solution,), diagnostics={}),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.build_action_catalog_from_turn",
        _catalog_from_turn,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.ship_first_overshoot.worthwhile_remainder_bound_for_turn",
        lambda *_args, **_kwargs: _open_bound(cap_2x=40),
    )
    turn = replace(sample_turn, minefields=(_minefield(units=50),))
    observation = _observation(
        military_delta_2x=400, warship_delta=1, military_partition_slack_2x=1
    )
    result, catalog, problem, attempted, _ = solve_with_policy_ladder(
        observation,
        turn,
        hopeless_context=_facts(max_owner_minefield_units=50),
        time_limit_seconds=60.0,
    )
    assert result.status == STATUS_MINE_SCORE_RESIDUAL
    assert result.solutions
    assert len(overshoot_steps) > 1
    assert PLANET_OR_STARBASE_POST_STEP_IDS.isdisjoint(attempted)
    payload = inference_result_to_api_payload(result, catalog, observation, turn, problem)
    assert payload["status"] == STATUS_MINE_SCORE_RESIDUAL
    assert payload["unexplainedMilitaryDelta2x"] == 20
    arithmetic = payload["solutions"][0]["militaryScoreArithmetic"]
    assert arithmetic["matchesObserved"] is False
    assert arithmetic["explainedMilitaryDelta2x"] == 420
    row = persisted_inference_row_from_wire_complete(
        {"type": "complete", **{k: v for k, v in payload.items() if k != "diagnostics"}}
    )
    assert row.status == STATUS_MINE_SCORE_RESIDUAL
    assert row.solutions
    assert row.unexplained_military_delta_2x == 20

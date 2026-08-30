"""Hopeless classifier and inference expensive-tier abort."""

from __future__ import annotations

import time

from api.analytics.military_score_inference.hopeless_classifier import (
    EXPENSIVE_TIER_STEP_IDS,
    MODERATE_RESIDUAL_MAX_POINTS,
    HopelessRowFacts,
    classify_hopeless_abort,
    leftover_2x_after_construction_envelope,
)
from api.analytics.military_score_inference.models import (
    InferenceResult,
    InferenceSolution,
    InferenceSolutionShipBuild,
)
from api.analytics.military_score_inference.policy_ladder import solve_with_policy_ladder
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_finish import (
    TierStepFinishMode,
    finish_tier_step,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_MINE_SCORE_RESIDUAL,
    STATUS_MODERATE_RESIDUAL,
    STATUS_NO_EXACT_SOLUTION,
)
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies

from tests.fixtures.military_score_inference import _observation

_LARGE_FIELD_MIN_UNITS = 1000


def _facts(**overrides: object) -> HopelessRowFacts:
    values: dict[str, object] = {
        "planet_delta": 0,
        "starbase_delta": 0,
        "sticky_prior": False,
        "max_owner_minefield_units": 0,
        "large_minefield_min_units": _LARGE_FIELD_MIN_UNITS,
    }
    values.update(overrides)
    return HopelessRowFacts(**values)


def test_decrease_beyond_moderate_floor_is_mine_score_residual() -> None:
    decision = classify_hopeless_abort(
        _facts(),
        leftover_2x=-(MODERATE_RESIDUAL_MAX_POINTS + 1) * 2,
        warship_delta=0,
    )
    assert decision.abort is True
    assert decision.status == STATUS_MINE_SCORE_RESIDUAL


def test_sticky_prior_aborts_either_remainder_sign() -> None:
    negative = classify_hopeless_abort(_facts(sticky_prior=True), leftover_2x=-40, warship_delta=0)
    positive = classify_hopeless_abort(_facts(sticky_prior=True), leftover_2x=80, warship_delta=0)
    assert negative.abort is True
    assert negative.status == STATUS_MINE_SCORE_RESIDUAL
    assert positive.abort is True
    assert positive.status == STATUS_MINE_SCORE_RESIDUAL


def test_large_minefield_observation_aborts_either_remainder_sign() -> None:
    negative = classify_hopeless_abort(
        _facts(max_owner_minefield_units=_LARGE_FIELD_MIN_UNITS),
        leftover_2x=-40,
        warship_delta=0,
    )
    positive = classify_hopeless_abort(
        _facts(max_owner_minefield_units=_LARGE_FIELD_MIN_UNITS),
        leftover_2x=80,
        warship_delta=0,
    )
    assert negative.abort is True
    assert negative.status == STATUS_MINE_SCORE_RESIDUAL
    assert positive.abort is True
    assert positive.status == STATUS_MINE_SCORE_RESIDUAL


def test_sub_threshold_minefield_probe_does_not_abort() -> None:
    decision = classify_hopeless_abort(
        _facts(max_owner_minefield_units=_LARGE_FIELD_MIN_UNITS - 1),
        leftover_2x=80,
        warship_delta=0,
    )
    assert decision.abort is False
    assert decision.status is None


def test_leftover_one_to_eleven_is_moderate_residual_without_sticky_or_large_field() -> None:
    low = classify_hopeless_abort(_facts(), leftover_2x=2, warship_delta=0)
    high = classify_hopeless_abort(
        _facts(), leftover_2x=-(MODERATE_RESIDUAL_MAX_POINTS * 2), warship_delta=0
    )
    assert low.abort is True
    assert low.status == STATUS_MODERATE_RESIDUAL
    assert high.abort is True
    assert high.status == STATUS_MODERATE_RESIDUAL


def test_positive_leftover_beyond_moderate_climbs_expensive() -> None:
    decision = classify_hopeless_abort(
        _facts(), leftover_2x=(MODERATE_RESIDUAL_MAX_POINTS + 1) * 2, warship_delta=0
    )
    assert decision.abort is False
    assert decision.status is None


def test_warship_count_drop_is_not_mine_shaped() -> None:
    decision = classify_hopeless_abort(_facts(), leftover_2x=-40, warship_delta=-1)
    assert decision.abort is False
    assert decision.status is None


def test_planet_count_drop_blocks_mine_shaped_path() -> None:
    decision = classify_hopeless_abort(_facts(planet_delta=-1), leftover_2x=-40, warship_delta=0)
    assert decision.abort is False


def test_starbase_count_drop_blocks_mine_shaped_path() -> None:
    decision = classify_hopeless_abort(_facts(starbase_delta=-1), leftover_2x=-40, warship_delta=0)
    assert decision.abort is False


def test_count_drop_still_aborts_when_sticky_or_large_field() -> None:
    sticky = classify_hopeless_abort(_facts(sticky_prior=True), leftover_2x=-40, warship_delta=-1)
    large = classify_hopeless_abort(
        _facts(planet_delta=-1, max_owner_minefield_units=_LARGE_FIELD_MIN_UNITS),
        leftover_2x=-40,
        warship_delta=0,
    )
    assert sticky.status == STATUS_MINE_SCORE_RESIDUAL
    assert large.status == STATUS_MINE_SCORE_RESIDUAL


def test_leftover_after_envelope_is_military_minus_min_warship_fill() -> None:
    leftover = leftover_2x_after_construction_envelope(
        military_delta_2x=100,
        warship_delta=1,
        min_warship_score_delta_2x=400,
    )
    assert leftover == -300


def test_flat_counts_leave_observation_military_as_leftover() -> None:
    leftover = leftover_2x_after_construction_envelope(
        military_delta_2x=-24,
        warship_delta=0,
        min_warship_score_delta_2x=400,
    )
    assert leftover == -24


def test_recent_window_uses_max_owner_units_and_ignores_other_owners(sample_turn) -> None:
    from dataclasses import replace

    from api.analytics.military_score_inference.hopeless_classifier import (
        max_owner_minefield_units_in_recent_window,
    )
    from api.models.space import Minefield

    owner_id = 8

    def _turn_with_fields(*fields: Minefield):
        return replace(sample_turn, minefields=list(fields))

    prior = _turn_with_fields(
        Minefield(
            id=1,
            ownerid=owner_id,
            isweb=False,
            ishidden=False,
            units=400,
            infoturn=109,
            friendlycode="???",
            x=0,
            y=0,
            radius=1,
        ),
        Minefield(
            id=2,
            ownerid=4,
            isweb=False,
            ishidden=False,
            units=9000,
            infoturn=109,
            friendlycode="???",
            x=0,
            y=0,
            radius=1,
        ),
    )
    current = _turn_with_fields(
        Minefield(
            id=3,
            ownerid=owner_id,
            isweb=False,
            ishidden=False,
            units=1200,
            infoturn=111,
            friendlycode="???",
            x=0,
            y=0,
            radius=1,
        )
    )
    maximum = max_owner_minefield_units_in_recent_window(
        owner_id=owner_id,
        host_turn=111,
        window_turns=3,
        turns_by_number={109: prior, 111: current},
    )
    assert maximum == 1200


def test_cheap_exact_clears_n_window_carry_forward(sample_turn) -> None:
    from dataclasses import replace

    from api.analytics.military_score_inference.hopeless_classifier import (
        max_owner_minefield_units_in_recent_window,
    )
    from api.models.space import Minefield

    owner_id = 8
    prior = replace(
        sample_turn,
        minefields=[
            Minefield(
                id=1,
                ownerid=owner_id,
                isweb=False,
                ishidden=False,
                units=4000,
                infoturn=110,
                friendlycode="???",
                x=0,
                y=0,
                radius=1,
            )
        ],
    )
    current = replace(
        sample_turn,
        minefields=[
            Minefield(
                id=2,
                ownerid=owner_id,
                isweb=False,
                ishidden=False,
                units=200,
                infoturn=111,
                friendlycode="???",
                x=0,
                y=0,
                radius=1,
            )
        ],
    )
    maximum = max_owner_minefield_units_in_recent_window(
        owner_id=owner_id,
        host_turn=111,
        window_turns=3,
        turns_by_number={110: prior, 111: current},
        exact_host_turns=frozenset({110}),
    )
    assert maximum == 200


def test_below_envelope_decrease_is_mine_score_residual() -> None:
    leftover = leftover_2x_after_construction_envelope(
        military_delta_2x=100,
        warship_delta=1,
        min_warship_score_delta_2x=400,
    )
    decision = classify_hopeless_abort(_facts(), leftover_2x=leftover, warship_delta=1)
    assert decision.status == STATUS_MINE_SCORE_RESIDUAL


def _emit_mock_solver_solutions(result: InferenceResult, **kwargs) -> InferenceResult:
    on_solution = kwargs.get("on_solution")
    if on_solution is not None:
        for solution in result.solutions:
            on_solution(solution)
    return result


def _unsat_every_tier(monkeypatch) -> None:
    def _solve_side_effect(_problem, **kwargs):
        return _emit_mock_solver_solutions(
            InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )


def test_expensive_tiers_are_not_entered_on_mine_residual_abort(sample_turn, monkeypatch) -> None:
    _unsat_every_tier(monkeypatch)
    observation = _observation(military_delta_2x=-40, warship_delta=0)
    result, _, _, attempted, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
        hopeless_context=_facts(),
        time_limit_seconds=60.0,
    )
    assert result.status == STATUS_MINE_SCORE_RESIDUAL
    assert "full_components" in attempted
    assert EXPENSIVE_TIER_STEP_IDS.isdisjoint(attempted)


def test_expensive_tiers_are_not_entered_on_moderate_residual_abort(
    sample_turn, monkeypatch
) -> None:
    _unsat_every_tier(monkeypatch)
    observation = _observation(military_delta_2x=-10, warship_delta=0)
    result, _, _, attempted, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
        hopeless_context=_facts(),
        time_limit_seconds=60.0,
    )
    assert result.status == STATUS_MODERATE_RESIDUAL
    assert "full_components" in attempted
    assert EXPENSIVE_TIER_STEP_IDS.isdisjoint(attempted)


def test_positive_leftover_still_climbs_expensive_tiers(sample_turn, monkeypatch) -> None:
    _unsat_every_tier(monkeypatch)
    observation = _observation(military_delta_2x=80, warship_delta=0)
    result, _, _, attempted, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
        hopeless_context=_facts(),
        time_limit_seconds=60.0,
    )
    assert result.status == STATUS_NO_EXACT_SOLUTION
    assert EXPENSIVE_TIER_STEP_IDS.issubset(attempted)


def test_abort_uses_catalog_envelope_leftover_not_raw_military(sample_turn, monkeypatch) -> None:
    """Abort leftover is observation minus catalog min fill, not a snapshot leftover.

    Positive warship_delta with raw military leftover that would climb expensive,
    while envelope leftover is a mine-shaped decrease. Would fail if abort used
    leftover_2x stored on row facts (built without the catalog envelope).
    """
    _unsat_every_tier(monkeypatch)
    min_fill_2x = 400
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_admission.min_warship_score_delta_2x",
        lambda _catalog: min_fill_2x,
    )
    military_delta_2x = 100
    warship_delta = 1
    observation = _observation(military_delta_2x=military_delta_2x, warship_delta=warship_delta)
    raw_leftover = leftover_2x_after_construction_envelope(military_delta_2x, warship_delta)
    envelope_leftover = leftover_2x_after_construction_envelope(
        military_delta_2x,
        warship_delta,
        min_fill_2x,
    )
    assert raw_leftover == military_delta_2x
    assert envelope_leftover != raw_leftover
    assert (
        classify_hopeless_abort(
            _facts(), leftover_2x=raw_leftover, warship_delta=warship_delta
        ).abort
        is False
    )
    assert (
        classify_hopeless_abort(
            _facts(), leftover_2x=envelope_leftover, warship_delta=warship_delta
        ).status
        == STATUS_MINE_SCORE_RESIDUAL
    )
    result, _, _, attempted, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
        hopeless_context=_facts(),
        time_limit_seconds=60.0,
    )
    assert result.status == STATUS_MINE_SCORE_RESIDUAL
    assert "full_components" in attempted
    assert EXPENSIVE_TIER_STEP_IDS.isdisjoint(attempted)


def _finish_full_components(
    sample_turn,
    *,
    finish_mode: TierStepFinishMode,
    skipped: bool = False,
    new_exact_before_step: int | None = None,
) -> tuple[PolicyLadderState, int]:
    """Close ``full_components`` on a ladder that would abort if the classifier ran."""
    steps = tuple(resolve_tier_policies())
    full_index = next(i for i, step in enumerate(steps) if step.id == "full_components")
    state = PolicyLadderState(
        policy_steps=steps,
        hopeless_context=_facts(),
        last_status=STATUS_NO_EXACT_SOLUTION,
        next_step_index=full_index,
    )
    finish_tier_step(
        state,
        policy_step=steps[full_index],
        policy_step_index=full_index,
        catalog=None,
        turn=sample_turn,
        observation=_observation(military_delta_2x=-40, warship_delta=0),
        seed_count=0,
        band_residual_2x=None,
        step_started_at=time.monotonic(),
        held_count_before=0,
        newly_admitted=[],
        skipped=skipped,
        finish_mode=finish_mode,
        new_exact_before_step=new_exact_before_step,
    )
    return state, full_index


def test_skip_of_full_components_does_not_abort(sample_turn) -> None:
    """Skipped last cheap step is not cheap-unsat; expensive tiers remain on the ladder."""
    state, full_index = _finish_full_components(
        sample_turn,
        finish_mode=TierStepFinishMode.SKIP,
        skipped=True,
    )
    remaining_ids = {step.id for step in state.policy_steps[state.next_step_index :]}
    assert state.ladder_early_stop_reason != "expensive_tier_abort"
    assert state.last_status == STATUS_NO_EXACT_SOLUTION
    assert state.ladder_complete is False
    assert state.next_step_index == full_index + 1
    assert EXPENSIVE_TIER_STEP_IDS.issubset(remaining_ids)


def test_budget_stop_of_full_components_does_not_abort(sample_turn) -> None:
    """Zero-spendable BUDGET_STOP of the last cheap step is not cheap-unsat."""
    state, full_index = _finish_full_components(
        sample_turn,
        finish_mode=TierStepFinishMode.BUDGET_STOP,
        skipped=True,
    )
    remaining_ids = {step.id for step in state.policy_steps[state.next_step_index :]}
    assert state.ladder_early_stop_reason != "expensive_tier_abort"
    assert state.last_status == STATUS_NO_EXACT_SOLUTION
    assert state.ladder_complete is False
    assert state.next_step_index == full_index + 1
    assert EXPENSIVE_TIER_STEP_IDS.issubset(remaining_ids)


def test_complete_of_full_components_still_aborts_when_classifier_fires(sample_turn) -> None:
    """Same setup as skip/budget-stop: COMPLETE of cheap-unsat still aborts."""
    state, _full_index = _finish_full_components(
        sample_turn,
        finish_mode=TierStepFinishMode.COMPLETE,
        new_exact_before_step=0,
    )
    assert state.ladder_early_stop_reason == "expensive_tier_abort"
    assert state.last_status == STATUS_MINE_SCORE_RESIDUAL
    assert state.ladder_complete is True


def test_cheap_exact_does_not_fire_classifier(sample_turn, monkeypatch) -> None:
    ship_exact = InferenceResult(
        status=STATUS_EXACT,
        solutions=(
            InferenceSolution(
                objective_value=-50,
                actions=(),
                ship_builds=(
                    InferenceSolutionShipBuild(
                        combo_id="combo_exact",
                        label="Exact",
                        count=1,
                        hull_id=1,
                        engine_id=1,
                        beam_id=None,
                        torp_id=None,
                        beam_count=0,
                        launcher_count=0,
                    ),
                ),
            ),
        ),
        diagnostics={},
    )

    def _solve_side_effect(problem, **kwargs):
        if problem.policy_step_id == "full_components":
            return _emit_mock_solver_solutions(ship_exact, **kwargs)
        return _emit_mock_solver_solutions(
            InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
            **kwargs,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.solve_inference_problem",
        _solve_side_effect,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_admission."
        "solution_satisfies_exact_hard_equalities",
        lambda solution, observation, catalog: True,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder."
        "solution_satisfies_exact_hard_equalities",
        lambda solution, observation, catalog: True,
    )
    observation = _observation(military_delta_2x=-40, warship_delta=0)
    result, _, _, attempted, _ = solve_with_policy_ladder(
        observation,
        sample_turn,
        hopeless_context=_facts(sticky_prior=True),
        time_limit_seconds=60.0,
    )
    assert result.status == STATUS_EXACT
    assert EXPENSIVE_TIER_STEP_IDS.isdisjoint(attempted)


def _minefield(*, owner_id: int, units: int, field_id: int = 1) -> object:
    from api.models.space import Minefield

    return Minefield(
        id=field_id,
        ownerid=owner_id,
        isweb=False,
        ishidden=False,
        units=units,
        infoturn=111,
        friendlycode="???",
        x=0,
        y=0,
        radius=1,
    )


def test_sample_turn_count_drops_block_auto_built_mine_shaped_abort(
    sample_turn, monkeypatch
) -> None:
    from dataclasses import replace

    from api.analytics.military_score_inference.hopeless_classifier import (
        scoreboard_count_deltas,
    )

    planet_delta, starbase_delta = scoreboard_count_deltas(sample_turn, 8)
    assert planet_delta < 0 or starbase_delta < 0
    _unsat_every_tier(monkeypatch)
    observation = _observation(military_delta_2x=-40, warship_delta=0)
    result, _, _, attempted, _ = solve_with_policy_ladder(
        observation,
        replace(sample_turn, minefields=[]),
        time_limit_seconds=60.0,
    )
    assert result.status == STATUS_NO_EXACT_SOLUTION
    assert EXPENSIVE_TIER_STEP_IDS.issubset(attempted)


def test_yaml_override_lowers_large_minefield_observation_gate(tmp_path, sample_turn) -> None:
    from dataclasses import replace

    from api.analytics.military_score_inference.hopeless_classifier import (
        hopeless_context_for_row,
    )

    policy_path = tmp_path / "tier_policy.yaml"
    policy_path.write_text(
        "\n".join(
            [
                "solverThresholds:",
                "  shipOnlyExactEarlyStopMinPlausibility: -300",
                "  noNewExactSignaturesEarlyStopMinPlausibility: -300",
                "  recentMinefieldObservationTurns: 3",
                "  largeMinefieldObservationMinUnits: 500",
                "",
            ]
        )
    )
    observation = _observation(military_delta_2x=80, warship_delta=0)
    turn = replace(sample_turn, minefields=[_minefield(owner_id=8, units=500)])
    context = hopeless_context_for_row(observation, turn, policy_path=policy_path)
    assert context.large_minefield_min_units == 500
    assert context.max_owner_minefield_units == 500
    decision = classify_hopeless_abort(
        context,
        leftover_2x=observation.military_delta_2x,
        warship_delta=observation.warship_delta,
    )
    assert decision.abort is True
    assert decision.status == STATUS_MINE_SCORE_RESIDUAL


def test_hopeless_context_reads_sticky_prior_from_persistence(sample_turn) -> None:
    from api.analytics.military_score_inference.hopeless_classifier import (
        hopeless_context_for_row,
    )

    class _StickyReader:
        def get_row(self, game_id: int, perspective: int, host_turn: int, player_id: int) -> None:
            return None

        def has_mine_residual_sticky_prior(
            self, game_id: int, perspective: int, host_turn: int, player_id: int
        ) -> bool:
            return True

    observation = _observation(military_delta_2x=80, warship_delta=0)
    context = hopeless_context_for_row(
        observation,
        sample_turn,
        persistence=_StickyReader(),
        game_id=1,
        perspective=8,
    )
    assert context.sticky_prior is True
    decision = classify_hopeless_abort(
        context,
        leftover_2x=observation.military_delta_2x,
        warship_delta=observation.warship_delta,
    )
    assert decision.status == STATUS_MINE_SCORE_RESIDUAL


def test_exact_persist_clears_n_window_in_hopeless_context(sample_turn) -> None:
    from dataclasses import replace

    from api.analytics.military_score_inference.hopeless_classifier import (
        exact_host_turns_from_persistence,
        hopeless_context_for_row,
    )
    from api.analytics.military_score_inference.models import InferenceObservation

    class _ExactPriorRow:
        status = STATUS_EXACT

    class _ExactPriorReader:
        def get_row(
            self, game_id: int, perspective: int, host_turn: int, player_id: int
        ) -> object | None:
            if host_turn == 110:
                return _ExactPriorRow()
            return None

        def has_mine_residual_sticky_prior(
            self, game_id: int, perspective: int, host_turn: int, player_id: int
        ) -> bool:
            return False

    persistence = _ExactPriorReader()
    assert exact_host_turns_from_persistence(
        persistence,
        game_id=1,
        perspective=8,
        player_id=8,
        host_turn=111,
        window_turns=3,
    ) == frozenset({110})

    prior = replace(sample_turn, minefields=[_minefield(owner_id=8, units=4000)])
    current = replace(sample_turn, minefields=[_minefield(owner_id=8, units=200)])

    def load_scoreboard_turn(turn_number: int):
        if turn_number == 110:
            return prior
        return None

    observation = InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=80,
        warship_delta=0,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=3,
        is_after_ship_limit=False,
        military_partition_slack_2x=0,
    )
    context = hopeless_context_for_row(
        observation,
        current,
        load_scoreboard_turn=load_scoreboard_turn,
        persistence=persistence,
        game_id=1,
        perspective=8,
    )
    assert context.max_owner_minefield_units == 200
    assert (
        classify_hopeless_abort(
            context,
            leftover_2x=observation.military_delta_2x,
            warship_delta=observation.warship_delta,
        ).abort
        is False
    )

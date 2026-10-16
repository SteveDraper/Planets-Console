"""Fittings outside the military window are removed before the CP-SAT model is built."""

from api.analytics.military_score_inference.military_score_window import (
    OvershootMilitaryScoreWindow,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.ranking_heuristics import (
    ship_build_objective_coefficient,
)
from api.analytics.military_score_inference.reachable_fittings import reachable_ship_fittings
from api.analytics.military_score_inference.solver import solve_inference_problem


def _observation(
    *,
    military_delta_2x: int,
    warship_delta: int = 1,
    freighter_delta: int = 0,
) -> InferenceObservation:
    return InferenceObservation(
        player_id=1,
        turn=10,
        military_delta_2x=military_delta_2x,
        warship_delta=warship_delta,
        freighter_delta=freighter_delta,
        priority_point_delta=0,
        starbases_owned=4,
        is_after_ship_limit=False,
    )


def _ship(
    combo_id: str,
    score_delta_2x: int,
    *,
    probability_weight: int = 10,
    upper_bound: int = 1,
    lower_bound: int = 0,
) -> ShipBuildCombo:
    return ShipBuildCombo(
        combo_id=combo_id,
        hull_id=1,
        engine_id=1,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
        labels=(combo_id,),
        score_delta_2x=score_delta_2x,
        warship_delta=1,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        probability_weight=probability_weight,
    )


def _problem(
    combos: tuple[ShipBuildCombo, ...],
    actions: tuple[CandidateAction, ...] = (),
    *,
    military_delta_2x: int,
    warship_delta: int = 1,
    window: OvershootMilitaryScoreWindow | None = None,
) -> InferenceProblem:
    return InferenceProblem(
        observation=_observation(
            military_delta_2x=military_delta_2x,
            warship_delta=warship_delta,
        ),
        aggregate_actions=actions,
        ship_build_combos=combos,
        military_score_window=window or OvershootMilitaryScoreWindow(cap_2x=380),
    )


def test_one_warship_window_drops_fittings_torpedoes_cannot_save() -> None:
    """The median admit shape: one warship, torpedoes add at most 6,320."""
    torpedoes = CandidateAction(
        id="ship_torps_loaded_6",
        label="Mark 4",
        score_delta_2x=56,
        upper_bound=40,
    )
    heavier = CandidateAction(
        id="ship_torps_loaded_9",
        label="Mark 7",
        score_delta_2x=102,
        upper_bound=40,
    )
    too_small = _ship("q_tanker", 544)
    just_under = _ship("refinery_short", 11_664)
    just_inside = _ship("refinery_full", 11_700)
    chosen = _ship("golem", 17_634)
    already_inside = _ship("golem_heavy", 18_350)
    too_large = _ship("merlin", 29_474)
    # Observed rise 17,998. Overshoot cap 380 starts the window at 18,000.
    problem = _problem(
        (too_small, just_under, just_inside, chosen, already_inside, too_large),
        (torpedoes, heavier),
        military_delta_2x=17_998,
    )

    kept = [combo.combo_id for combo in reachable_ship_fittings(problem, problem.ship_build_combos)]

    assert kept == ["refinery_full", "golem", "golem_heavy"]


def test_freighter_loss_does_not_keep_fittings_outside_the_window() -> None:
    """A freighter loss is one ship per count and adds no military score."""
    freighter_loss = CandidateAction(
        id="ship_loss:freighter:point:0",
        label="Freighter loss",
        score_delta_2x=0,
        freighter_delta=-1,
        upper_bound=2,
    )
    too_small = _ship("q_tanker", 544)
    kept_ship = _ship("golem_heavy", 18_350)
    too_large = _ship("merlin", 29_474)
    problem = _problem(
        (too_small, kept_ship, too_large),
        (freighter_loss,),
        military_delta_2x=17_998,
    )

    kept = [combo.combo_id for combo in reachable_ship_fittings(problem, problem.ship_build_combos)]

    assert kept == ["golem_heavy"]


def test_warship_loss_keeps_the_full_catalog() -> None:
    """A departing warship can subtract military, so the per-ship bound does not apply."""
    warship_loss = CandidateAction(
        id="ship_loss:warship:envelope:0:1000",
        label="Warship loss",
        score_delta_2x=0,
        warship_delta=-1,
        score_delta_2x_min=-1_000,
        score_delta_2x_max=0,
        upper_bound=1,
    )
    ships = (_ship("q_tanker", 544), _ship("golem", 17_634), _ship("merlin", 29_474))
    problem = _problem(ships, (warship_loss,), military_delta_2x=17_998)

    kept = [combo.combo_id for combo in reachable_ship_fittings(problem, problem.ship_build_combos)]

    assert kept == ["q_tanker", "golem", "merlin"]


def test_second_warship_can_carry_a_fitting_that_is_short_alone() -> None:
    cheap = _ship("cheap", 100)
    partner = _ship("partner", 900)
    # Exact window is the default. Two warships must total 1,000.
    problem = InferenceProblem(
        observation=_observation(military_delta_2x=1_000, warship_delta=2),
        aggregate_actions=(),
        ship_build_combos=(cheap, partner),
    )

    kept = [combo.combo_id for combo in reachable_ship_fittings(problem, problem.ship_build_combos)]

    assert kept == ["cheap", "partner"]


def test_zero_score_acquisition_keeps_a_ship_that_needs_no_partner_score() -> None:
    ship = _ship("ship", 1_000, upper_bound=1)
    acquisition = CandidateAction(
        id="acquired:warship:from:16",
        label="Acquired warship",
        score_delta_2x=0,
        warship_delta=1,
        upper_bound=1,
    )
    problem = InferenceProblem(
        observation=_observation(military_delta_2x=1_000, warship_delta=2),
        aggregate_actions=(acquisition,),
        ship_build_combos=(ship,),
    )

    kept = [combo.combo_id for combo in reachable_ship_fittings(problem, problem.ship_build_combos)]

    assert kept == ["ship"]


def test_forced_lower_bound_stays_even_when_the_score_misses_the_window() -> None:
    forced = _ship("forced", 100, lower_bound=1)
    problem = InferenceProblem(
        observation=_observation(military_delta_2x=1_000),
        aggregate_actions=(),
        ship_build_combos=(forced,),
    )

    kept = [combo.combo_id for combo in reachable_ship_fittings(problem, problem.ship_build_combos)]

    assert kept == ["forced"]


def test_dropped_fitting_still_sets_the_ranking_scale() -> None:
    """A heavier fitting outside the window still penalizes the ship that remains.

    The acquisition explains the same military rise with no ship penalty. If the
    dropped fitting's weight were forgotten, the kept ship would tie the
    acquisition at objective 0 and could be returned instead.
    """
    keeper = _ship("keeper", 1_000, probability_weight=10)
    outsider = _ship("outsider", 100, probability_weight=500)
    acquisition = CandidateAction(
        id="acquired:warship:from:16",
        label="Acquired warship",
        score_delta_2x=1_000,
        warship_delta=1,
        upper_bound=1,
    )
    problem = InferenceProblem(
        observation=_observation(military_delta_2x=1_000),
        aggregate_actions=(acquisition,),
        ship_build_combos=(keeper, outsider),
    )
    expected_ship_coefficient = ship_build_objective_coefficient(
        keeper,
        max_combo_weight=500,
        heuristics=problem.ranking_heuristics,
    )

    result = solve_inference_problem(problem)

    assert result.diagnostics["catalogShipFitCount"] == 2
    assert result.diagnostics["reachableShipFitCount"] == 1
    assert result.solutions
    assert result.solutions[0].ship_builds == ()
    assert result.solutions[0].objective_value == 0
    assert expected_ship_coefficient < 0

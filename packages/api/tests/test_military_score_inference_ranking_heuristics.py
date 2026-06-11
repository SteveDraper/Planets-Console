"""Tests for military score inference ranking heuristics (issue #85)."""

from api.analytics.military_score_inference.accelerated_start import accelerated_inference_segments
from api.analytics.military_score_inference.probability_bucket_defaults import (
    PLANET_DEFENSE_POST_BUCKETS,
    SHIP_TORPEDO_BUCKETS,
    STARBASE_DEFENSE_POST_BUCKETS,
)
from api.analytics.military_score_inference.inference_accelerated import (
    run_accelerated_segment_policy_ladder,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    InferenceProblem,
    InferenceSolutionShipBuild,
    ProbabilityBucket,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.ranking_heuristics import (
    InferenceRankingHeuristics,
    TierOverflowBand,
    active_ranking_bin_indicators,
    build_tier_aware_probability_buckets,
    compute_bin_penalty_objective_contribution,
    compute_parsimony_objective_contribution,
    partial_weapon_slot_penalty_for_fit,
    ranking_heuristics_diagnostics_payload,
)
from api.analytics.military_score_inference.scoring import (
    LOADED_SHIP_FIGHTER_SCORE_DELTA_2X,
    PLANET_DEFENSE_POST_SCORE_DELTA_2X,
    STARBASE_DEFENSE_POST_SCORE_DELTA_2X,
    STARBASE_FIGHTER_SCORE_DELTA_2X,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_NO_EXACT_SOLUTION,
    _objective_value,
    solve_inference_problem,
)
from api.analytics.military_score_inference.tier_policy import (
    compute_aggregate_admission_caps,
    resolve_tier_policies,
)


def _observation(
    *,
    military_delta_2x: int = 0,
    warship_delta: int = 0,
    freighter_delta: int = 0,
    starbases_owned: int = 3,
) -> InferenceObservation:
    return InferenceObservation(
        player_id=1,
        turn=5,
        military_delta_2x=military_delta_2x,
        warship_delta=warship_delta,
        freighter_delta=freighter_delta,
        priority_point_delta=0,
        starbases_owned=starbases_owned,
        is_after_ship_limit=False,
    )


def _problem(
    observation: InferenceObservation,
    *aggregate_actions: CandidateAction,
    ship_build_combos: tuple[ShipBuildCombo, ...] = (),
    probability_buckets_by_action_id: dict[str, tuple[ProbabilityBucket, ...]] | None = None,
    tier_overflow_by_action_id: dict[str, TierOverflowBand] | None = None,
    admission_caps_by_action_id: dict[str, int] | None = None,
    ranking_heuristics: InferenceRankingHeuristics | None = None,
    max_solutions: int = 20,
) -> InferenceProblem:
    return InferenceProblem(
        observation=observation,
        aggregate_actions=aggregate_actions,
        ship_build_combos=ship_build_combos,
        probability_buckets_by_action_id=probability_buckets_by_action_id or {},
        tier_overflow_by_action_id=tier_overflow_by_action_id or {},
        admission_caps_by_action_id=admission_caps_by_action_id or {},
        ranking_heuristics=ranking_heuristics or InferenceRankingHeuristics(),
        max_solutions=max_solutions,
        time_limit_seconds=1.0,
    )


def test_diversity_cap_blocks_three_torp_types():
    torp_score = 100
    torp_actions = tuple(
        CandidateAction(
            id=f"ship_torps_loaded_{torp_id}",
            label=f"Torpedoes {torp_id}",
            score_delta_2x=torp_score,
            upper_bound=2,
            probability_weight=10,
        )
        for torp_id in (1, 2, 3)
    )
    observation = _observation(military_delta_2x=3 * torp_score)
    buckets = {action.id: (ProbabilityBucket("modest load", 0, 2, 70),) for action in torp_actions}
    result = solve_inference_problem(
        _problem(
            observation,
            *torp_actions,
            probability_buckets_by_action_id=buckets,
        )
    )

    if result.status == STATUS_EXACT:
        active_torp_types = sum(
            1
            for action in result.solutions[0].actions
            if action.action_id.startswith("ship_torps_loaded_")
        )
        assert active_torp_types <= 2
    else:
        assert result.status == STATUS_NO_EXACT_SOLUTION


def test_ship_build_outranks_noise_multiset():
    slack_one = CandidateAction(
        id="planet_defense_posts_added_total",
        label="Planet defense posts",
        score_delta_2x=200,
        upper_bound=2,
        probability_weight=40,
    )
    slack_two = CandidateAction(
        id="starbase_fighters_added_total",
        label="Starbase fighters",
        score_delta_2x=200,
        upper_bound=2,
        probability_weight=40,
    )
    ship_combo_no_warship = ShipBuildCombo(
        combo_id="combo_warship",
        hull_id=1,
        engine_id=1,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
        labels=("Build warship",),
        score_delta_2x=400,
        warship_delta=0,
        upper_bound=1,
        probability_weight=85,
    )
    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=400, warship_delta=0),
            slack_one,
            slack_two,
            ship_build_combos=(ship_combo_no_warship,),
            max_solutions=5,
        )
    )

    assert result.status == STATUS_EXACT
    assert len(result.solutions) >= 2
    assert result.solutions[0].ship_builds
    assert result.solutions[0].ship_builds[0].combo_id == "combo_warship"
    assert result.solutions[0].objective_value > result.solutions[1].objective_value


def test_parsimony_allows_planet_and_starbase_defense():
    planet = CandidateAction(
        id="planet_defense_posts_added_total",
        label="Planet defense posts",
        score_delta_2x=PLANET_DEFENSE_POST_SCORE_DELTA_2X,
        upper_bound=10,
        probability_weight=10,
    )
    starbase = CandidateAction(
        id="starbase_defense_posts_added_total",
        label="Starbase defense posts",
        score_delta_2x=STARBASE_DEFENSE_POST_SCORE_DELTA_2X,
        upper_bound=10,
        probability_weight=10,
    )
    military_delta_2x = (
        5 * PLANET_DEFENSE_POST_SCORE_DELTA_2X + 3 * STARBASE_DEFENSE_POST_SCORE_DELTA_2X
    )
    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=military_delta_2x),
            planet,
            starbase,
            probability_buckets_by_action_id={
                planet.id: PLANET_DEFENSE_POST_BUCKETS,
                starbase.id: STARBASE_DEFENSE_POST_BUCKETS,
            },
            max_solutions=5,
        )
    )

    assert result.status == STATUS_EXACT
    counts = {action.action_id: action.count for action in result.solutions[0].actions}
    assert counts.get(planet.id, 0) > 0
    assert counts.get(starbase.id, 0) > 0


def test_tier_overflow_penalizes_count_above_admission_cap():
    heuristics = InferenceRankingHeuristics(parsimony_per_active_slack_type=-5)
    admission_cap = 16
    current_cap = 100
    planet = CandidateAction(
        id="planet_defense_posts_added_total",
        label="Planet defense posts",
        score_delta_2x=PLANET_DEFENSE_POST_SCORE_DELTA_2X,
        upper_bound=current_cap,
        probability_weight=10,
    )
    alt_slack = CandidateAction(
        id="starbase_defense_posts_added_total",
        label="Starbase defense posts substitute",
        score_delta_2x=PLANET_DEFENSE_POST_SCORE_DELTA_2X,
        upper_bound=admission_cap + 18,
        probability_weight=10,
    )
    buckets, overflow_band = build_tier_aware_probability_buckets(
        PLANET_DEFENSE_POST_BUCKETS,
        admission_cap=admission_cap,
        current_cap=current_cap,
        overflow_marginal_weight=heuristics.tier_overflow_marginal_weight,
    )
    assert overflow_band is not None
    military_delta_2x = 50 * PLANET_DEFENSE_POST_SCORE_DELTA_2X
    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=military_delta_2x),
            planet,
            alt_slack,
            probability_buckets_by_action_id={
                planet.id: buckets,
            },
            tier_overflow_by_action_id={planet.id: overflow_band},
            admission_caps_by_action_id={planet.id: admission_cap},
            ranking_heuristics=heuristics,
            max_solutions=5,
        )
    )

    assert result.status == STATUS_EXACT
    counts = {action.action_id: action.count for action in result.solutions[0].actions}
    assert counts[planet.id] <= admission_cap
    assert counts[planet.id] + counts[alt_slack.id] == 50

    overflow_problem = _problem(
        _observation(military_delta_2x=military_delta_2x),
        planet,
        alt_slack,
        probability_buckets_by_action_id={planet.id: buckets},
        tier_overflow_by_action_id={planet.id: overflow_band},
        ranking_heuristics=heuristics,
    )
    overflow_only_counts = {action.id: 0 for action in overflow_problem.aggregate_actions}
    overflow_only_counts[planet.id] = 50
    overflow_only_objective = _objective_value(
        overflow_problem,
        overflow_only_counts,
        (),
    )
    assert result.solutions[0].objective_value >= overflow_only_objective


def test_fighter_channel_diversity_cap():
    fighter_actions = (
        CandidateAction(
            id="starbase_fighters_added_total",
            label="Starbase fighters",
            score_delta_2x=STARBASE_FIGHTER_SCORE_DELTA_2X,
            upper_bound=1,
            probability_weight=10,
        ),
        CandidateAction(
            id="ship_fighters_added_total",
            label="Ship fighters",
            score_delta_2x=LOADED_SHIP_FIGHTER_SCORE_DELTA_2X,
            upper_bound=1,
            probability_weight=10,
        ),
        CandidateAction(
            id="fighters_starbase_to_ship",
            label="Fighters starbase to ship",
            score_delta_2x=STARBASE_FIGHTER_SCORE_DELTA_2X,
            upper_bound=1,
            probability_weight=15,
        ),
    )
    military_delta_2x = sum(action.score_delta_2x for action in fighter_actions)
    result = solve_inference_problem(
        _problem(_observation(military_delta_2x=military_delta_2x), *fighter_actions)
    )

    if result.status == STATUS_EXACT:
        active_types = sum(1 for action in result.solutions[0].actions if action.count > 0)
        assert active_types <= 2
    else:
        assert result.status == STATUS_NO_EXACT_SOLUTION


def test_objective_value_includes_parsimony():
    slack_one = CandidateAction(
        id="planet_defense_posts_added_total",
        label="Planet defense posts",
        score_delta_2x=200,
        upper_bound=1,
        probability_weight=50,
    )
    slack_two = CandidateAction(
        id="starbase_fighters_added_total",
        label="Starbase fighters",
        score_delta_2x=200,
        upper_bound=1,
        probability_weight=50,
    )
    problem = _problem(
        _observation(military_delta_2x=400),
        slack_one,
        slack_two,
    )
    result = solve_inference_problem(problem)

    assert result.status == STATUS_EXACT
    solution = result.solutions[0]
    action_counts = {action.id: 0 for action in problem.aggregate_actions}
    for action in solution.actions:
        action_counts[action.action_id] = action.count
    recomputed = _objective_value(problem, action_counts, solution.ship_builds)
    assert recomputed == solution.objective_value
    parsimony = compute_parsimony_objective_contribution(
        action_counts,
        problem.ranking_heuristics,
    )
    assert parsimony == -100


def test_top_k_still_descending_objective_order():
    preferred = CandidateAction(
        id="planet_defense_posts_added_total",
        label="Planet defense posts",
        score_delta_2x=PLANET_DEFENSE_POST_SCORE_DELTA_2X,
        upper_bound=20,
        probability_weight=100,
    )
    alternate = CandidateAction(
        id="starbase_defense_posts_added_total",
        label="Starbase defense posts",
        score_delta_2x=STARBASE_DEFENSE_POST_SCORE_DELTA_2X,
        upper_bound=20,
        probability_weight=50,
    )
    military_delta_2x = 10 * PLANET_DEFENSE_POST_SCORE_DELTA_2X
    result = solve_inference_problem(
        _problem(
            _observation(military_delta_2x=military_delta_2x),
            preferred,
            alternate,
            probability_buckets_by_action_id={
                preferred.id: PLANET_DEFENSE_POST_BUCKETS,
                alternate.id: STARBASE_DEFENSE_POST_BUCKETS,
            },
            max_solutions=3,
        )
    )

    assert result.status == STATUS_EXACT
    objective_values = [solution.objective_value for solution in result.solutions]
    assert objective_values == sorted(objective_values, reverse=True)


def test_compute_aggregate_admission_caps_uses_first_allowlist_appearance():
    steps = resolve_tier_policies()
    full_catalog_index = next(
        index for index, step in enumerate(steps) if step.id == "full_catalog_exact"
    )
    caps = compute_aggregate_admission_caps(steps, full_catalog_index)

    assert caps["planet_defense_posts_added_total"] == 16
    assert caps["ship_torps_per_type"] == 40


def test_ranking_heuristics_diagnostics_payload_shape():
    payload = ranking_heuristics_diagnostics_payload(
        InferenceRankingHeuristics(),
        admission_caps_by_action_id={"planet_defense_posts_added_total": 16},
    )

    assert payload["parsimonyPerActiveSlackType"] == -50
    assert payload["partialWeaponSlotPenaltyPerLine"] == -25
    assert payload["tierOverflowMarginalWeight"] == 50
    assert payload["admissionCaps"] == {"planet_defense_posts_added_total": 16}
    assert len(payload["diversityCaps"]) == 2


def test_partial_weapon_slot_penalty_applies_per_underfilled_line():
    heuristics = InferenceRankingHeuristics()
    assert (
        partial_weapon_slot_penalty_for_fit(
            beam_count=2,
            launcher_count=3,
            hull_beam_slots=4,
            hull_launcher_slots=3,
            heuristics=heuristics,
        )
        == -25
    )
    assert (
        partial_weapon_slot_penalty_for_fit(
            beam_count=2,
            launcher_count=1,
            hull_beam_slots=4,
            hull_launcher_slots=3,
            heuristics=heuristics,
        )
        == -50
    )
    assert (
        partial_weapon_slot_penalty_for_fit(
            beam_count=4,
            launcher_count=3,
            hull_beam_slots=4,
            hull_launcher_slots=3,
            heuristics=heuristics,
        )
        == 0
    )
    assert (
        partial_weapon_slot_penalty_for_fit(
            beam_count=0,
            launcher_count=0,
            hull_beam_slots=4,
            hull_launcher_slots=3,
            heuristics=heuristics,
        )
        == 0
    )


def test_partial_weapon_slot_fill_ranks_below_full_slots():
    from api.analytics.military_score_inference.solver import _objective_value

    full_fit = ShipBuildCombo(
        combo_id="combo_full",
        hull_id=24,
        engine_id=1,
        beam_id=1,
        torp_id=1,
        beam_count=4,
        launcher_count=3,
        hull_beam_slots=4,
        hull_launcher_slots=3,
        labels=("Full fit",),
        score_delta_2x=400,
        warship_delta=1,
        upper_bound=1,
        probability_weight=85,
    )
    partial_fit = ShipBuildCombo(
        combo_id="combo_partial",
        hull_id=24,
        engine_id=1,
        beam_id=1,
        torp_id=1,
        beam_count=2,
        launcher_count=1,
        hull_beam_slots=4,
        hull_launcher_slots=3,
        labels=("Partial fit",),
        score_delta_2x=400,
        warship_delta=1,
        upper_bound=1,
        probability_weight=85,
    )
    problem = _problem(
        _observation(military_delta_2x=400, warship_delta=1),
        ship_build_combos=(full_fit, partial_fit),
        max_solutions=2,
    )
    full_build = InferenceSolutionShipBuild(
        combo_id="combo_full",
        label="Full fit",
        count=1,
        hull_id=24,
        engine_id=1,
        beam_id=1,
        torp_id=1,
        beam_count=4,
        launcher_count=3,
    )
    partial_build = InferenceSolutionShipBuild(
        combo_id="combo_partial",
        label="Partial fit",
        count=1,
        hull_id=24,
        engine_id=1,
        beam_id=1,
        torp_id=1,
        beam_count=2,
        launcher_count=1,
    )
    assert _objective_value(problem, {}, (full_build,)) == 0
    assert _objective_value(problem, {}, (partial_build,)) == -50


def test_ranking_bin_penalty_is_per_bin_not_per_unit():
    assert active_ranking_bin_indicators(1, PLANET_DEFENSE_POST_BUCKETS) == (1, 0, 0)
    assert active_ranking_bin_indicators(10, PLANET_DEFENSE_POST_BUCKETS) == (1, 0, 0)
    assert active_ranking_bin_indicators(100, PLANET_DEFENSE_POST_BUCKETS) == (0, 0, 1)

    ten_posts = compute_bin_penalty_objective_contribution(
        {"planet_defense_posts_added_total": 10},
        {"planet_defense_posts_added_total": PLANET_DEFENSE_POST_BUCKETS},
    )
    hundred_posts = compute_bin_penalty_objective_contribution(
        {"planet_defense_posts_added_total": 100},
        {"planet_defense_posts_added_total": PLANET_DEFENSE_POST_BUCKETS},
    )
    assert ten_posts == 0
    assert hundred_posts == -95
    assert ten_posts > hundred_posts


def test_628580_accel_window_ranks_ten_planet_defense_first():
    from tests.inference_corpus.fixtures import load_turn_fixture

    player_id = 1
    score_turn = load_turn_fixture("628580/1/turns/3.json")
    score = next(row for row in score_turn.scores if row.ownerid == player_id)
    accel = next(
        segment
        for segment in accelerated_inference_segments(score, score_turn)
        if segment.segment_id == "accel_window"
    )
    assert accel.military_delta_2x == 110
    assert accel.freighter_delta == 1

    result = run_accelerated_segment_policy_ladder(
        score,
        score_turn,
        accel,
        max_solutions=20,
        time_limit_seconds=30.0,
    )

    assert result.result.status == "exact"
    top = result.result.solutions[0]
    action_counts = {action.action_id: action.count for action in top.actions}
    ship_counts = {build.combo_id: build.count for build in top.ship_builds}
    torp_total = sum(
        count
        for action_id, count in action_counts.items()
        if action_id.startswith("ship_torps_loaded_")
    )

    assert action_counts.get("planet_defense_posts_added_total") == 10
    assert torp_total == 0
    assert ship_counts.get("combo_freighter") == 1


def test_ship_torpedo_modest_bin_covers_typical_load_counts():
    from api.analytics.military_score_inference.ranking_heuristics import (
        active_ranking_bin_index,
        max_marginal_weight,
        ranking_penalty_from_marginal_weight,
    )

    assert SHIP_TORPEDO_BUCKETS[0].upper_count == 40
    assert active_ranking_bin_index(30, SHIP_TORPEDO_BUCKETS) == 0
    assert active_ranking_bin_index(41, SHIP_TORPEDO_BUCKETS) == 1
    max_weight = max_marginal_weight(SHIP_TORPEDO_BUCKETS)
    assert (
        ranking_penalty_from_marginal_weight(
            SHIP_TORPEDO_BUCKETS[1].marginal_weight,
            max_marginal_weight=max_weight,
        )
        == 0
    )

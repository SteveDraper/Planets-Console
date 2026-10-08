"""Held score-class labels refresh when a later tier adds a better fitting."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from api.analytics.military_score_inference.actions import (
    ActionCatalog,
    build_inference_problem,
)
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.held_score_equivalent_relabel import (
    relabeled_solutions_for_widened_classes,
)
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceResult,
    InferenceSolution,
    InferenceSolutionShipBuild,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.policy_ladder_tier_step import (
    run_policy_ladder_tier_step,
)
from api.analytics.military_score_inference.ranked_solution_buffer import (
    SolutionSignature,
    admit_ranked_solutions,
    solution_signature,
)
from api.analytics.military_score_inference.solver import STATUS_NO_EXACT_SOLUTION
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies

# Game 686688 turn 2, Birds (raceid 3): both fittings score exactly 2580 (2x = 5160).
EXACT_MILITARY_2X = 5160
BIRDS_RACE_ID = 3
FEARLESS_COMBO_ID = "combo_28_8_6_7_6_1"
ENLIGHTEN_COMBO_ID = "combo_106_9_3_6_5_1"
RELABELED_ORDER = (ENLIGHTEN_COMBO_ID, FEARLESS_COMBO_ID)


def _observation() -> InferenceObservation:
    return InferenceObservation(
        player_id=4,
        turn=2,
        military_delta_2x=EXACT_MILITARY_2X,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=1,
        is_after_ship_limit=False,
    )


def _combo(
    combo_id: str,
    hull_id: int,
    weight: int,
    *,
    score_delta_2x: int = EXACT_MILITARY_2X,
) -> ShipBuildCombo:
    return ShipBuildCombo(
        combo_id=combo_id,
        hull_id=hull_id,
        engine_id=9,
        beam_id=3,
        torp_id=6,
        beam_count=5,
        launcher_count=1,
        labels=(combo_id,),
        score_delta_2x=score_delta_2x,
        warship_delta=1,
        upper_bound=1,
        probability_weight=weight,
        hull_beam_slots=5,
        hull_launcher_slots=1,
    )


def _ship(combo: ShipBuildCombo) -> InferenceSolutionShipBuild:
    return InferenceSolutionShipBuild(
        combo_id=combo.combo_id,
        label=combo.labels[0],
        count=1,
        hull_id=combo.hull_id,
        engine_id=combo.engine_id,
        beam_id=combo.beam_id,
        torp_id=combo.torp_id,
        beam_count=combo.beam_count,
        launcher_count=combo.launcher_count,
    )


def _catalog(*combos: ShipBuildCombo) -> ActionCatalog:
    return ActionCatalog(
        aggregate_actions=(),
        ship_build_combos=combos,
        probability_buckets_by_action_id={},
    )


def _ship_combo_ids(solutions: Sequence[InferenceSolution]) -> tuple[str, ...]:
    return tuple(solution.ship_builds[0].combo_id for solution in solutions)


def _relabel_into_buffer(
    *held_rows: InferenceSolution,
    catalog: ActionCatalog,
    added_combo_ids: frozenset[str],
    overshoot_signatures: Collection[SolutionSignature] = frozenset(),
    max_solutions: int = 20,
) -> tuple[list[InferenceSolution], list[InferenceSolution]]:
    """Hold ``held_rows``, admit widened-class labels, and return the buffer plus new admits."""
    held: list[InferenceSolution] = []
    seen: set[SolutionSignature] = set()
    admit_ranked_solutions(held, seen, held_rows, max_solutions=max_solutions)
    admitted: list[InferenceSolution] = []
    admit_ranked_solutions(
        held,
        seen,
        relabeled_solutions_for_widened_classes(
            held,
            catalog,
            _observation(),
            added_combo_ids=added_combo_ids,
            overshoot_signatures=overshoot_signatures,
            race_id=BIRDS_RACE_ID,
            max_solutions=max_solutions,
        ),
        max_solutions=max_solutions,
        on_admitted=admitted.append,
    )
    return held, admitted


def test_wider_catalog_admits_higher_weight_label_of_held_score() -> None:
    fearless = _combo(FEARLESS_COMBO_ID, 28, weight=-1128)
    enlighten = _combo(ENLIGHTEN_COMBO_ID, 106, weight=-641)
    held, admitted = _relabel_into_buffer(
        InferenceSolution(
            objective_value=-668,
            actions=(),
            ship_builds=(_ship(fearless),),
        ),
        catalog=_catalog(fearless, enlighten),
        added_combo_ids=frozenset({ENLIGHTEN_COMBO_ID}),
    )

    assert _ship_combo_ids(held) == RELABELED_ORDER
    assert held[0].objective_value == 0
    assert _ship_combo_ids(admitted) == (ENLIGHTEN_COMBO_ID,)


def test_inserting_a_better_label_still_relabels_later_held_classes() -> None:
    fearless = _combo(FEARLESS_COMBO_ID, 28, weight=-1128)
    enlighten = _combo(ENLIGHTEN_COMBO_ID, 106, weight=-641)
    weak = _combo("combo_weak", 31, weight=-200, score_delta_2x=1000)
    strong = _combo("combo_strong", 33, weight=-10, score_delta_2x=1000)
    held, _ = _relabel_into_buffer(
        InferenceSolution(objective_value=-668, actions=(), ship_builds=(_ship(fearless),)),
        InferenceSolution(objective_value=-100, actions=(), ship_builds=(_ship(weak),)),
        catalog=_catalog(fearless, enlighten, weak, strong),
        added_combo_ids=frozenset({ENLIGHTEN_COMBO_ID, strong.combo_id}),
    )

    assert {ENLIGHTEN_COMBO_ID, "combo_strong"} <= set(_ship_combo_ids(held))


def test_added_combo_outside_held_score_class_is_ignored() -> None:
    fearless = _combo(FEARLESS_COMBO_ID, 28, weight=-1128)
    other_score = _combo("combo_other", 31, weight=0, score_delta_2x=1000)
    held, admitted = _relabel_into_buffer(
        InferenceSolution(
            objective_value=-668,
            actions=(),
            ship_builds=(_ship(fearless),),
        ),
        catalog=_catalog(fearless, other_score),
        added_combo_ids=frozenset({other_score.combo_id}),
    )

    assert _ship_combo_ids(held) == (FEARLESS_COMBO_ID,)
    assert admitted == []


def test_full_buffer_keeps_worse_new_label_out() -> None:
    enlighten = _combo(ENLIGHTEN_COMBO_ID, 106, weight=-641)
    fearless = _combo(FEARLESS_COMBO_ID, 28, weight=-1128)
    held, admitted = _relabel_into_buffer(
        InferenceSolution(
            objective_value=0,
            actions=(),
            ship_builds=(_ship(enlighten),),
        ),
        catalog=_catalog(enlighten, fearless),
        added_combo_ids=frozenset({FEARLESS_COMBO_ID}),
        max_solutions=1,
    )

    assert _ship_combo_ids(held) == (ENLIGHTEN_COMBO_ID,)
    assert admitted == []


def test_overshoot_tagged_held_row_is_not_relabeled() -> None:
    fearless = _combo(FEARLESS_COMBO_ID, 28, weight=-1128)
    enlighten = _combo(ENLIGHTEN_COMBO_ID, 106, weight=-641)
    weak = _combo("combo_weak", 31, weight=-200, score_delta_2x=1000)
    strong = _combo("combo_strong", 33, weight=-10, score_delta_2x=1000)
    held_fearless = InferenceSolution(
        objective_value=-668,
        actions=(),
        ship_builds=(_ship(fearless),),
        ship_first_family="mine_overshoot",
    )
    # Family tag alone does not exclude a row; only overshoot_signatures does.
    held_weak = InferenceSolution(
        objective_value=-100,
        actions=(),
        ship_builds=(_ship(weak),),
        ship_first_family="ammo_top_up",
    )
    held, admitted = _relabel_into_buffer(
        held_fearless,
        held_weak,
        catalog=_catalog(fearless, enlighten, weak, strong),
        added_combo_ids=frozenset({ENLIGHTEN_COMBO_ID, strong.combo_id}),
        overshoot_signatures={solution_signature(held_fearless)},
    )

    held_ids = set(_ship_combo_ids(held))
    assert _ship_combo_ids(admitted) == ("combo_strong",)
    assert ENLIGHTEN_COMBO_ID not in held_ids
    assert {FEARLESS_COMBO_ID, "combo_weak", "combo_strong"} <= held_ids
    fearless_row = next(
        solution for solution in held if solution.ship_builds[0].combo_id == FEARLESS_COMBO_ID
    )
    weak_row = next(
        solution for solution in held if solution.ship_builds[0].combo_id == "combo_weak"
    )
    assert fearless_row.ship_first_family == "mine_overshoot"
    assert weak_row.ship_first_family == "ammo_top_up"


def test_tier_step_relabels_before_search(sample_turn, monkeypatch) -> None:
    fearless = _combo(FEARLESS_COMBO_ID, 28, weight=-1128)
    enlighten = _combo(ENLIGHTEN_COMBO_ID, 106, weight=-641)
    wide_catalog = _catalog(fearless, enlighten)
    held_fearless = InferenceSolution(
        objective_value=-668,
        actions=(),
        ship_builds=(_ship(fearless),),
    )
    state = PolicyLadderState(policy_steps=tuple(resolve_tier_policies(None)[:1]))
    state.catalog = wide_catalog
    state.prior_combo_ids = frozenset({FEARLESS_COMBO_ID})
    state.merged_solutions = [held_fearless]
    state.seen_signatures = {solution_signature(held_fearless)}
    score = next(row for row in sample_turn.scores if row.ownerid == sample_turn.player.id)
    observation = build_inference_observation(score, sample_turn)
    admitted: list[InferenceSolution] = []
    seed_no_good_ids: list[tuple[str, ...]] = []
    merged_ids_at_solve: list[tuple[str, ...]] = []
    admitted_ids_at_solve: list[tuple[str, ...]] = []

    def fake_catalog(*_args, **_kwargs):
        return wide_catalog

    def fake_solve(*_args, **kwargs):
        seed_no_goods: Sequence[InferenceSolution] = kwargs["seed_no_good_solutions"]
        seed_no_good_ids.append(_ship_combo_ids(seed_no_goods))
        merged_ids_at_solve.append(_ship_combo_ids(state.merged_solutions))
        admitted_ids_at_solve.append(_ship_combo_ids(admitted))
        problem = build_inference_problem(observation, wide_catalog)
        return (
            InferenceResult(status=STATUS_NO_EXACT_SOLUTION, solutions=(), diagnostics={}),
            problem,
        )

    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step.build_action_catalog_from_turn",
        fake_catalog,
    )
    monkeypatch.setattr(
        "api.analytics.military_score_inference.policy_ladder_tier_step._solve_catalog",
        fake_solve,
    )

    run_policy_ladder_tier_step(
        state,
        observation,
        sample_turn,
        time_limit_seconds=None,
        on_admitted=admitted.append,
    )

    assert seed_no_good_ids
    assert set(seed_no_good_ids) == {RELABELED_ORDER}
    assert set(merged_ids_at_solve) == {RELABELED_ORDER}
    assert set(admitted_ids_at_solve) == {(ENLIGHTEN_COMBO_ID,)}
    assert _ship_combo_ids(admitted) == (ENLIGHTEN_COMBO_ID,)
    diagnostics = state.step_diagnostics[-1]
    assert diagnostics["newlyAdmittedCount"] == 1
    assert diagnostics["heldCountBefore"] == 1
    assert diagnostics["heldCountAfter"] == 2

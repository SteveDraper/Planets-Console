"""Ship-first family tag and stratified hold (#414 / design §3.11)."""

from __future__ import annotations

from api.analytics.military_score_inference.actions import ActionCatalog
from api.analytics.military_score_inference.inference_api_payload import (
    inference_result_to_api_payload,
)
from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceProblem,
    InferenceResult,
    InferenceSolution,
    InferenceSolutionAction,
    InferenceSolutionShipBuild,
    ShipBuildCombo,
    ShipFirstFamily,
)
from api.analytics.military_score_inference.ranked_solution_buffer import solution_signature
from api.analytics.military_score_inference.ship_first_family import (
    SHIP_FIRST_FAMILY_HOLD_FLOOR,
    admit_ship_first_ranked_solution,
    classify_ship_first_family,
    tag_ship_first_near_solution,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT, STATUS_MINE_SCORE_RESIDUAL
from api.serialization.inference_row_persistence import persisted_inference_row_from_wire_complete

from tests.fixtures.military_score_inference import _observation

_SHIP_ACTION_ID = "build_rush"
_TORP_ACTION_ID = "ship_torps_loaded_6"
_COMBO_ID = "combo_warship"


def _ship_action(*, score_delta_2x: int = 100) -> CandidateAction:
    return CandidateAction(
        id=_SHIP_ACTION_ID,
        label="Build Rush",
        score_delta_2x=score_delta_2x,
        warship_delta=1,
        upper_bound=1,
    )


def _torp_action(*, score_delta_2x: int = 40) -> CandidateAction:
    return CandidateAction(
        id=_TORP_ACTION_ID,
        label="Load Mark 7 Photon",
        score_delta_2x=score_delta_2x,
        upper_bound=40,
    )


def _combo(*, score_delta_2x: int = 80) -> ShipBuildCombo:
    return ShipBuildCombo(
        combo_id=_COMBO_ID,
        hull_id=1,
        engine_id=1,
        beam_id=None,
        torp_id=6,
        beam_count=0,
        launcher_count=2,
        labels=("Warship",),
        score_delta_2x=score_delta_2x,
        warship_delta=1,
        build_slot_usage=1,
        upper_bound=1,
    )


def _catalog(
    *,
    ship_score_2x: int = 100,
    torp_score_2x: int = 40,
    combo_score_2x: int = 80,
    include_combo: bool = False,
) -> ActionCatalog:
    combos = (_combo(score_delta_2x=combo_score_2x),) if include_combo else ()
    return ActionCatalog(
        aggregate_actions=(
            _ship_action(score_delta_2x=ship_score_2x),
            _torp_action(score_delta_2x=torp_score_2x),
        ),
        ship_build_combos=combos,
        probability_buckets_by_action_id={},
    )


def _solution(
    *,
    objective: int,
    ship_count: int = 1,
    torp_count: int = 0,
    combo_count: int = 0,
    action_id: str | None = None,
    family: ShipFirstFamily | None = None,
) -> InferenceSolution:
    actions: list[InferenceSolutionAction] = []
    if ship_count:
        actions.append(
            InferenceSolutionAction(
                action_id=action_id or _SHIP_ACTION_ID,
                label="Build Rush",
                count=ship_count,
            )
        )
    if torp_count:
        actions.append(
            InferenceSolutionAction(
                action_id=_TORP_ACTION_ID,
                label="Load Mark 7 Photon",
                count=torp_count,
            )
        )
    builds = ()
    if combo_count:
        builds = (
            InferenceSolutionShipBuild(
                combo_id=_COMBO_ID,
                label="Warship",
                count=combo_count,
                hull_id=1,
                engine_id=1,
                torp_id=6,
                launcher_count=2,
            ),
        )
    return InferenceSolution(
        objective_value=objective,
        actions=tuple(actions),
        ship_builds=builds,
        ship_first_family=family,
    )


def test_torps_inflating_leftover_still_mine_overshoot() -> None:
    observation = _observation(military_delta_2x=100, military_partition_slack_2x=1)
    catalog = _catalog(ship_score_2x=120, torp_score_2x=40)
    solution = _solution(objective=-10, ship_count=1, torp_count=1)

    assert classify_ship_first_family(solution, observation, catalog) == "mine_overshoot"


def test_torps_closing_the_window_are_ammo_top_up() -> None:
    observation = _observation(military_delta_2x=100, military_partition_slack_2x=1)
    catalog = _catalog(ship_score_2x=100, torp_score_2x=40)
    solution = _solution(objective=-10, ship_count=1, torp_count=1)

    assert classify_ship_first_family(solution, observation, catalog) == "ammo_top_up"


def test_ship_builds_count_as_non_torp_even_with_launchers() -> None:
    observation = _observation(military_delta_2x=100, military_partition_slack_2x=1)
    catalog = _catalog(include_combo=True, combo_score_2x=120, torp_score_2x=40)
    solution = _solution(objective=-10, ship_count=0, torp_count=1, combo_count=1)

    assert classify_ship_first_family(solution, observation, catalog) == "mine_overshoot"


def test_leftover_0_exact_is_not_tagged() -> None:
    observation = _observation(military_delta_2x=100, military_partition_slack_2x=1)
    catalog = _catalog(ship_score_2x=100)
    solution = _solution(objective=0, ship_count=1, torp_count=0)

    assert classify_ship_first_family(solution, observation, catalog) is None
    tagged = tag_ship_first_near_solution(solution, observation, catalog)
    assert tagged.ship_first_family is None


def test_ammo_top_up_may_span_most_of_leftover_no_torp_cap() -> None:
    observation = _observation(military_delta_2x=100, military_partition_slack_2x=1)
    catalog = _catalog(ship_score_2x=90, torp_score_2x=200)
    solution = _solution(objective=-10, ship_count=1, torp_count=1)

    assert classify_ship_first_family(solution, observation, catalog) == "ammo_top_up"


def test_stratified_hold_keeps_floor_when_both_families_present() -> None:
    leftovers = {
        "mine_0": 4,
        "mine_1": 5,
        "mine_2": 6,
        "ammo_0": 40,
        "ammo_1": 41,
        "ammo_2": 42,
        "mine_heavy": 2,
        "ammo_worse": 80,
    }
    held: list[InferenceSolution] = []
    seen: set[tuple[tuple[str, int], ...]] = set()

    def leftover_of(solution: InferenceSolution) -> int:
        return leftovers[solution.actions[0].action_id]

    for index in range(SHIP_FIRST_FAMILY_HOLD_FLOOR):
        mine = _solution(
            objective=-1,
            action_id=f"mine_{index}",
            family="mine_overshoot",
        )
        ammo = _solution(
            objective=-100,
            action_id=f"ammo_{index}",
            family="ammo_top_up",
        )
        assert admit_ship_first_ranked_solution(
            held,
            seen,
            mine,
            max_solutions=6,
            leftover_2x=leftover_of,
        )
        assert admit_ship_first_ranked_solution(
            held,
            seen,
            ammo,
            max_solutions=6,
            leftover_2x=leftover_of,
        )

    families = [solution.ship_first_family for solution in held]
    assert families.count("mine_overshoot") == SHIP_FIRST_FAMILY_HOLD_FLOOR
    assert families.count("ammo_top_up") == SHIP_FIRST_FAMILY_HOLD_FLOOR

    heavier_mine = _solution(objective=10, action_id="mine_heavy", family="mine_overshoot")
    assert admit_ship_first_ranked_solution(
        held,
        seen,
        heavier_mine,
        max_solutions=6,
        leftover_2x=leftover_of,
    )
    families = [solution.ship_first_family for solution in held]
    assert families.count("ammo_top_up") == SHIP_FIRST_FAMILY_HOLD_FLOOR
    assert families.count("mine_overshoot") == SHIP_FIRST_FAMILY_HOLD_FLOOR
    assert any(solution.actions[0].action_id == "mine_heavy" for solution in held)

    worse_ammo = _solution(objective=-200, action_id="ammo_worse", family="ammo_top_up")
    assert (
        admit_ship_first_ranked_solution(
            held,
            seen,
            worse_ammo,
            max_solutions=6,
            leftover_2x=leftover_of,
        )
        is False
    )
    families = [solution.ship_first_family for solution in held]
    assert families.count("ammo_top_up") == SHIP_FIRST_FAMILY_HOLD_FLOOR
    assert families.count("mine_overshoot") == SHIP_FIRST_FAMILY_HOLD_FLOOR


def test_stratified_hold_fills_rest_of_k_by_weight_then_leftover() -> None:
    held: list[InferenceSolution] = []
    seen: set[tuple[tuple[str, int], ...]] = set()
    leftovers: dict[str, int] = {}

    def leftover_of(solution: InferenceSolution) -> int:
        return leftovers[solution.actions[0].action_id]

    for index in range(3):
        mine = _solution(objective=100, action_id=f"mine_{index}", family="mine_overshoot")
        ammo = _solution(objective=100, action_id=f"ammo_{index}", family="ammo_top_up")
        leftovers[mine.actions[0].action_id] = index
        leftovers[ammo.actions[0].action_id] = index
        admit_ship_first_ranked_solution(held, seen, mine, max_solutions=8, leftover_2x=leftover_of)
        admit_ship_first_ranked_solution(held, seen, ammo, max_solutions=8, leftover_2x=leftover_of)

    heavier_rest = _solution(objective=50, action_id="mine_heavier", family="mine_overshoot")
    leftovers["mine_heavier"] = 4
    worse_leftover = _solution(objective=40, action_id="mine_worse_left", family="mine_overshoot")
    leftovers["mine_worse_left"] = 9
    better_leftover = _solution(objective=40, action_id="mine_better_left", family="mine_overshoot")
    leftovers["mine_better_left"] = 1

    assert admit_ship_first_ranked_solution(
        held, seen, heavier_rest, max_solutions=8, leftover_2x=leftover_of
    )
    assert admit_ship_first_ranked_solution(
        held, seen, worse_leftover, max_solutions=8, leftover_2x=leftover_of
    )
    assert admit_ship_first_ranked_solution(
        held, seen, better_leftover, max_solutions=8, leftover_2x=leftover_of
    )

    held_ids = [solution.actions[0].action_id for solution in held]
    assert "mine_heavier" in held_ids
    assert "mine_better_left" in held_ids
    assert "mine_worse_left" not in held_ids
    families = [solution.ship_first_family for solution in held]
    assert families.count("mine_overshoot") == 5
    assert families.count("ammo_top_up") == 3


def test_second_family_fills_floor_inside_a_full_one_family_buffer() -> None:
    held: list[InferenceSolution] = []
    seen: set[tuple[tuple[str, int], ...]] = set()
    leftovers: dict[str, int] = {}

    def leftover_of(solution: InferenceSolution) -> int:
        return leftovers[solution.actions[0].action_id]

    for index in range(6):
        mine = _solution(objective=100 - index, action_id=f"mine_{index}", family="mine_overshoot")
        leftovers[mine.actions[0].action_id] = index
        admit_ship_first_ranked_solution(held, seen, mine, max_solutions=6, leftover_2x=leftover_of)
    assert {solution.ship_first_family for solution in held} == {"mine_overshoot"}

    for index in range(3):
        ammo = _solution(objective=-50, action_id=f"ammo_{index}", family="ammo_top_up")
        leftovers[ammo.actions[0].action_id] = 20 + index
        assert admit_ship_first_ranked_solution(
            held, seen, ammo, max_solutions=6, leftover_2x=leftover_of
        )

    families = [solution.ship_first_family for solution in held]
    assert families.count("mine_overshoot") == 3
    assert families.count("ammo_top_up") == 3


def test_one_family_may_fill_all_k() -> None:
    held: list[InferenceSolution] = []
    seen: set[tuple[tuple[str, int], ...]] = set()

    def leftover_of(_solution: InferenceSolution) -> int:
        return 10

    for index in range(5):
        mine = _solution(objective=-index, action_id=f"mine_{index}", family="mine_overshoot")
        assert admit_ship_first_ranked_solution(
            held, seen, mine, max_solutions=4, leftover_2x=leftover_of
        ) is (index < 4)

    assert len(held) == 4
    assert {solution.ship_first_family for solution in held} == {"mine_overshoot"}
    held_ids = [solution.actions[0].action_id for solution in held]
    assert "mine_4" not in held_ids
    assert "mine_0" in held_ids


def test_wire_persists_ship_first_family_and_omits_it_on_exact(sample_turn) -> None:
    observation = _observation(
        military_delta_2x=100, warship_delta=1, military_partition_slack_2x=1
    )
    catalog = _catalog(ship_score_2x=120, torp_score_2x=40)
    tagged = tag_ship_first_near_solution(
        _solution(objective=-10, ship_count=1, torp_count=1),
        observation,
        catalog,
    )
    assert tagged.ship_first_family == "mine_overshoot"
    result = InferenceResult(
        status=STATUS_MINE_SCORE_RESIDUAL,
        solutions=(tagged,),
        diagnostics={},
    )
    problem = InferenceProblem(
        observation=observation,
        aggregate_actions=catalog.aggregate_actions,
    )
    payload = inference_result_to_api_payload(result, catalog, observation, sample_turn, problem)
    assert payload["solutions"][0]["shipFirstFamily"] == "mine_overshoot"
    row = persisted_inference_row_from_wire_complete(
        {"type": "complete", **{k: v for k, v in payload.items() if k != "diagnostics"}}
    )
    assert row.solutions[0]["shipFirstFamily"] == "mine_overshoot"

    exact = tag_ship_first_near_solution(
        _solution(objective=0, ship_count=1, torp_count=0),
        _observation(military_delta_2x=100, warship_delta=1, military_partition_slack_2x=1),
        _catalog(ship_score_2x=100),
    )
    exact_payload = inference_result_to_api_payload(
        InferenceResult(status=STATUS_EXACT, solutions=(exact,), diagnostics={}),
        _catalog(ship_score_2x=100),
        _observation(military_delta_2x=100, warship_delta=1, military_partition_slack_2x=1),
        sample_turn,
        InferenceProblem(
            observation=_observation(
                military_delta_2x=100, warship_delta=1, military_partition_slack_2x=1
            ),
            aggregate_actions=_catalog(ship_score_2x=100).aggregate_actions,
        ),
    )
    assert "shipFirstFamily" not in exact_payload["solutions"][0]
    assert solution_signature(tagged) != solution_signature(exact)

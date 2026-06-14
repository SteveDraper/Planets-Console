"""Unit tests for inference top-K ranking check (#65)."""

from tests.inference_corpus.verify import (
    check_ground_truth_in_top_k,
    solution_to_ground_truth,
)


def test_solution_to_ground_truth_merges_actions_and_ship_builds():
    solution = {
        "actions": [{"actionId": "ship_fighters_added_total", "count": 2}],
        "shipBuilds": [{"comboId": "combo_13_9_3_6_8_6", "count": 1}],
    }
    assert solution_to_ground_truth(solution) == (
        ("combo_13_9_3_6_8_6", 1),
        ("ship_fighters_added_total", 2),
    )


def test_solution_to_ground_truth_ignores_zero_counts():
    solution = {
        "actions": [{"actionId": "ship_fighters_added_total", "count": 0}],
        "shipBuilds": [],
    }
    assert solution_to_ground_truth(solution) == ()


def test_check_ground_truth_in_top_k_hit_at_rank_one():
    ground_truth = (("combo_1_2_none_none_0_0", 1),)
    solutions = [
        {"actions": [], "shipBuilds": [{"comboId": "combo_1_2_none_none_0_0", "count": 1}]},
        {"actions": [], "shipBuilds": [{"comboId": "combo_9_1_none_none_0_0", "count": 1}]},
    ]
    hit, rank = check_ground_truth_in_top_k(ground_truth, solutions, k=3)
    assert hit is True
    assert rank == 1


def test_check_ground_truth_in_top_k_miss_beyond_k():
    ground_truth = (("combo_9_1_none_none_0_0", 1),)
    solutions = [
        {"actions": [], "shipBuilds": [{"comboId": "combo_1_2_none_none_0_0", "count": 1}]},
        {"actions": [], "shipBuilds": [{"comboId": "combo_9_1_none_none_0_0", "count": 1}]},
    ]
    hit, rank = check_ground_truth_in_top_k(ground_truth, solutions, k=1)
    assert hit is False
    assert rank == 2


def test_check_ground_truth_in_top_k_absent_from_all_solutions():
    ground_truth = (("combo_missing", 1),)
    solutions = [
        {"actions": [], "shipBuilds": [{"comboId": "combo_1_2_none_none_0_0", "count": 1}]},
    ]
    hit, rank = check_ground_truth_in_top_k(ground_truth, solutions, k=3)
    assert hit is False
    assert rank is None

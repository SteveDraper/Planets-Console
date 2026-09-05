"""Worthwhile remainder bound from mine-stock histograms (#412 / design §3.9)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.military_score_inference.models import (
    InferenceObservation,
    InferenceProblem,
)
from api.analytics.military_score_inference.policy_ladder import finalize_policy_ladder_result
from api.analytics.military_score_inference.policy_ladder_state import PolicyLadderState
from api.analytics.military_score_inference.prior_mining.mine_stock import (
    MineStockAsset,
    MineStockHistograms,
    write_mine_stock_asset,
)
from api.analytics.military_score_inference.solver import STATUS_NO_EXACT_SOLUTION
from api.analytics.military_score_inference.worthwhile_remainder_bound import (
    compute_worthwhile_remainder_bound,
    leftover_military_2x_from_lost_units,
)
from api.concepts.game_category import GAME_CATEGORY_RULES_VERSION, GameCategory
from api.concepts.minefield_decay import (
    equal_split_field_units,
    lost_units_after_default_decay,
)

RACE_ID = 4
BLOB_UNITS = 200
EQUAL_SPLIT_FIELDS = 2
# Independent of production convert: blob of 200 loses 11 units; two fields of 100 lose 12.
BLOB_LOST_UNITS = 11
EQUAL_SPLIT_LOST_UNITS = 12
BLOB_LEFTOVER_2X = 5.94
EQUAL_SPLIT_LEFTOVER_2X = 6.48
# Visible 400 + 20: per-field lost 21 + 2; equal-split of 420 into 2 fields loses 22.
OBSERVED_EXACT_LOST = 23
OBSERVED_EQUAL_SPLIT_LOST = 22
OBSERVED_EXACT_LEFTOVER_2X = 12.42
OBSERVED_EQUAL_SPLIT_LEFTOVER_2X = 11.88


def _asset(histograms: MineStockHistograms) -> MineStockAsset:
    return MineStockAsset(
        version=1,
        category=GameCategory.STANDARD.value,
        game_category_rules_version=GAME_CATEGORY_RULES_VERSION,
        histograms=histograms,
    )


def _cell(
    *, total_units: dict[int, float], field_count: dict[int, float]
) -> dict[str, dict[int, float]]:
    return {"totalUnits": dict(total_units), "fieldCount": dict(field_count)}


def _positive_stock_cell(count: float = 80.0) -> dict[str, dict[int, float]]:
    return _cell(
        total_units={BLOB_UNITS: count},
        field_count={EQUAL_SPLIT_FIELDS: count},
    )


def _empty_stock_cell(count: float = 20.0) -> dict[str, dict[int, float]]:
    return _cell(total_units={0: count}, field_count={0: count})


def _bound(
    histograms: MineStockHistograms,
    *,
    host_turn: int,
    observed_field_units: tuple[int, ...] = (),
    slack_2x: int = 1,
    race_id: int = RACE_ID,
):
    return compute_worthwhile_remainder_bound(
        _asset(histograms),
        race_id=race_id,
        host_turn=host_turn,
        observed_field_units=observed_field_units,
        slack_2x=slack_2x,
    )


def test_blob_under_counts_per_field_minus_one_versus_equal_split():
    assert lost_units_after_default_decay(BLOB_UNITS) == BLOB_LOST_UNITS
    assert equal_split_field_units(BLOB_UNITS, EQUAL_SPLIT_FIELDS) == (100, 100)
    assert (
        sum(lost_units_after_default_decay(units) for units in (100, 100)) == EQUAL_SPLIT_LOST_UNITS
    )
    assert leftover_military_2x_from_lost_units(BLOB_LOST_UNITS) == pytest.approx(BLOB_LEFTOVER_2X)
    assert leftover_military_2x_from_lost_units(EQUAL_SPLIT_LOST_UNITS) == pytest.approx(
        EQUAL_SPLIT_LEFTOVER_2X
    )


def test_empirical_p90_drops_empty_stock_and_uses_equal_split_not_blob():
    histograms = {
        RACE_ID: {
            40: _cell(
                total_units={0: 10.0, BLOB_UNITS: 90.0},
                field_count={0: 10.0, EQUAL_SPLIT_FIELDS: 90.0},
            )
        }
    }
    bound = _bound(histograms, host_turn=40, slack_2x=0)
    assert bound.p90_total_units == BLOB_UNITS
    assert bound.p90_field_count == EQUAL_SPLIT_FIELDS
    assert bound.empirical_leftover_2x == pytest.approx(EQUAL_SPLIT_LEFTOVER_2X)
    assert bound.empirical_leftover_2x != pytest.approx(BLOB_LEFTOVER_2X)


def test_sparse_missing_cell_is_one_hundred_percent_interpolant():
    histograms = {
        RACE_ID: {
            10: _empty_stock_cell(20.0),
            40: _positive_stock_cell(80.0),
        }
    }
    bound = _bound(histograms, host_turn=25, slack_2x=0)
    assert bound.n_total == 0
    assert bound.mixture_weight == 0.0
    assert bound.empirical_leftover_2x == 0.0
    assert bound.interpolant_leftover_2x == pytest.approx(3.24)
    assert bound.mixed_leftover_2x == pytest.approx(3.24)


def test_empty_stock_cell_mixes_zero_empirical_with_interpolant():
    histograms = {
        RACE_ID: {
            10: _empty_stock_cell(20.0),
            40: _positive_stock_cell(80.0),
        }
    }
    bound = _bound(histograms, host_turn=10, slack_2x=0)
    assert bound.n_total == 20
    assert bound.mixture_weight == 0.5
    assert bound.empirical_leftover_2x == 0.0
    assert bound.interpolant_leftover_2x == 0.0
    assert bound.mixed_leftover_2x == 0.0


def test_isotonic_holds_last_knot_instead_of_extrapolating():
    histograms = {
        RACE_ID: {
            10: _empty_stock_cell(20.0),
            40: _positive_stock_cell(80.0),
        }
    }
    bound = _bound(histograms, host_turn=100, slack_2x=0)
    assert bound.n_total == 0
    assert bound.interpolant_leftover_2x == pytest.approx(EQUAL_SPLIT_LEFTOVER_2X)
    assert bound.mixed_leftover_2x == pytest.approx(EQUAL_SPLIT_LEFTOVER_2X)
    extrapolated = EQUAL_SPLIT_LEFTOVER_2X + (100 - 40) * (EQUAL_SPLIT_LEFTOVER_2X / 30)
    assert bound.interpolant_leftover_2x != pytest.approx(extrapolated)


def test_isotonic_pools_decreasing_leftover_knots():
    histograms = {
        RACE_ID: {
            10: _positive_stock_cell(20.0),
            20: _empty_stock_cell(20.0),
        }
    }
    bound = _bound(histograms, host_turn=20, slack_2x=0)
    assert bound.empirical_leftover_2x == 0.0
    assert bound.interpolant_leftover_2x == pytest.approx(3.24)
    assert bound.mixture_weight == 0.5
    assert bound.mixed_leftover_2x == pytest.approx(1.62)


def test_observed_stock_floor_uses_exact_per_field_decay_not_equal_split():
    histograms = {RACE_ID: {40: _empty_stock_cell(100.0)}}
    prior_only = _bound(histograms, host_turn=40, observed_field_units=(), slack_2x=0)
    assert prior_only.observed_floor_2x == 0.0
    assert prior_only.bound_2x == 0.0

    floored = _bound(histograms, host_turn=40, observed_field_units=(400, 20), slack_2x=0)
    assert (
        lost_units_after_default_decay(400) + lost_units_after_default_decay(20)
        == OBSERVED_EXACT_LOST
    )
    assert (
        sum(lost_units_after_default_decay(units) for units in equal_split_field_units(420, 2))
        == OBSERVED_EQUAL_SPLIT_LOST
    )
    assert floored.observed_floor_2x == pytest.approx(OBSERVED_EXACT_LEFTOVER_2X)
    assert floored.observed_floor_2x != pytest.approx(OBSERVED_EQUAL_SPLIT_LEFTOVER_2X)
    assert floored.bound_2x == pytest.approx(OBSERVED_EXACT_LEFTOVER_2X)
    assert floored.mixed_leftover_2x == 0.0


def test_cap_at_or_below_slack_empties_overshoot_window():
    histograms = {RACE_ID: {40: _positive_stock_cell(80.0)}}
    open_window = _bound(histograms, host_turn=40, slack_2x=5)
    assert open_window.cap_2x == 6
    assert open_window.overshoot_window_empty is False

    closed_window = _bound(histograms, host_turn=40, slack_2x=6)
    assert closed_window.cap_2x == 6
    assert closed_window.overshoot_window_empty is True


def test_load_mine_stock_for_category_reads_sibling_yaml(tmp_path: Path):
    from api.analytics.military_score_inference.prior_mining.mine_stock import (
        load_mine_stock_for_category,
    )

    histograms = {RACE_ID: {40: _positive_stock_cell(3.0)}}
    write_mine_stock_asset(tmp_path / "mine_stock_standard.yaml", _asset(histograms))
    asset, path, fell_back = load_mine_stock_for_category(GameCategory.STANDARD, base_dir=tmp_path)
    assert fell_back is False
    assert path == tmp_path / "mine_stock_standard.yaml"
    assert asset.histograms[RACE_ID][40]["totalUnits"][BLOB_UNITS] == 3.0


def test_load_mine_stock_for_category_falls_back_to_standard(tmp_path: Path):
    from api.analytics.military_score_inference.prior_mining.mine_stock import (
        load_mine_stock_for_category,
    )

    histograms = {RACE_ID: {40: _positive_stock_cell(3.0)}}
    write_mine_stock_asset(tmp_path / "mine_stock_standard.yaml", _asset(histograms))
    asset, path, fell_back = load_mine_stock_for_category(GameCategory.CAMPAIGN, base_dir=tmp_path)
    assert fell_back is True
    assert path == tmp_path / "mine_stock_standard.yaml"
    assert asset.histograms[RACE_ID][40]["totalUnits"][BLOB_UNITS] == 3.0


def test_ladder_diagnostics_record_remainder_bound(sample_turn, monkeypatch):
    from api.analytics.military_score_inference import worthwhile_remainder_bound as bound_mod
    from api.analytics.military_score_inference.actions import ActionCatalog

    player_id = sample_turn.player.id
    race_id = sample_turn.player.raceid
    asset = _asset({race_id: {sample_turn.settings.turn: _positive_stock_cell(80.0)}})

    def _fake_load(_category, *, base_dir=None):
        return asset, Path("mine_stock_standard.yaml"), False

    monkeypatch.setattr(bound_mod, "load_mine_stock_for_category", _fake_load)

    observation = InferenceObservation(
        player_id=player_id,
        turn=sample_turn.settings.turn,
        military_delta_2x=40,
        warship_delta=0,
        freighter_delta=0,
        priority_point_delta=0,
        starbases_owned=1,
        is_after_ship_limit=False,
        military_partition_slack_2x=1,
    )
    catalog = ActionCatalog((), (), {})
    problem = InferenceProblem(observation=observation, aggregate_actions=())
    state = PolicyLadderState(
        policy_steps=(),
        catalog=catalog,
        problem=problem,
        last_status=STATUS_NO_EXACT_SOLUTION,
        ladder_complete=True,
    )
    turn = replace(sample_turn, minefields=())
    result, *_ = finalize_policy_ladder_result(state, observation, turn)
    payload = result.diagnostics["worthwhileRemainderBound"]
    assert payload["cap2x"] == 6
    assert payload["overshootWindowEmpty"] is False
    assert payload["empiricalLeftover2x"] == pytest.approx(EQUAL_SPLIT_LEFTOVER_2X)

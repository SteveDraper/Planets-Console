"""Idle-dock PP equality lattice gate (#370)."""

from dataclasses import replace

from api.analytics.military_score_inference.idle_dock_pp import (
    idle_dock_implied_ships_built,
    is_idle_dock_queue,
    should_enforce_idle_dock_pp,
)
from api.analytics.military_score_inference.models import InferenceObservation


def _observation(
    *,
    priority_point_delta: int = 2,
    starbases_owned: int = 2,
    planet_delta: int = 0,
    starbase_delta: int = 0,
    is_after_ship_limit: bool = False,
) -> InferenceObservation:
    return InferenceObservation(
        player_id=8,
        turn=111,
        military_delta_2x=0,
        warship_delta=1,
        freighter_delta=0,
        priority_point_delta=priority_point_delta,
        starbases_owned=starbases_owned,
        is_after_ship_limit=is_after_ship_limit,
        planet_delta=planet_delta,
        starbase_delta=starbase_delta,
    )


def test_pq_ppq_shared_limit_is_idle_dock_queue(sample_turn):
    assert sample_turn.settings.productionqueue is True
    assert sample_turn.settings.planetaryproductionqueue is True
    assert sample_turn.settings.shiplimittype == 0
    assert is_idle_dock_queue(sample_turn.settings) is True


def test_enforce_on_even_lattice_without_planet_or_starbase_drop(sample_turn):
    assert should_enforce_idle_dock_pp(_observation(), sample_turn.settings) is True


def test_skip_odd_priority_points(sample_turn):
    assert (
        should_enforce_idle_dock_pp(
            _observation(priority_point_delta=1),
            sample_turn.settings,
        )
        is False
    )


def test_skip_classic_pbp(sample_turn):
    settings = replace(
        sample_turn.settings,
        productionqueue=False,
        planetaryproductionqueue=False,
    )
    assert is_idle_dock_queue(settings) is False
    assert should_enforce_idle_dock_pp(_observation(), settings) is False


def test_skip_pls(sample_turn):
    settings = replace(sample_turn.settings, shiplimittype=1)
    assert is_idle_dock_queue(settings) is False
    assert should_enforce_idle_dock_pp(_observation(), settings) is False


def test_skip_after_ship_limit(sample_turn):
    assert (
        should_enforce_idle_dock_pp(
            _observation(is_after_ship_limit=True),
            sample_turn.settings,
        )
        is False
    )


def test_skip_planet_count_drop(sample_turn):
    assert (
        should_enforce_idle_dock_pp(
            _observation(planet_delta=-1),
            sample_turn.settings,
        )
        is False
    )


def test_skip_starbase_count_drop(sample_turn):
    assert (
        should_enforce_idle_dock_pp(
            _observation(starbase_delta=-1),
            sample_turn.settings,
        )
        is False
    )


def test_implied_ships_built_on_lattice():
    assert idle_dock_implied_ships_built(_observation()) == 1
    assert idle_dock_implied_ships_built(_observation(priority_point_delta=0)) == 2
    assert idle_dock_implied_ships_built(_observation(priority_point_delta=4)) == 0


def test_implied_ships_built_off_lattice_is_none():
    assert idle_dock_implied_ships_built(_observation(priority_point_delta=1)) is None
    assert idle_dock_implied_ships_built(_observation(priority_point_delta=6)) is None
    assert idle_dock_implied_ships_built(_observation(starbases_owned=-1)) is None

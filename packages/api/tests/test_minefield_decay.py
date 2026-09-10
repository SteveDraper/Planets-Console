"""Minefield radius, default vs nebula decay, and nebula disk overlap."""

from __future__ import annotations

from dataclasses import dataclass

from api.concepts.minefield_decay import (
    DEFAULT_MINEFIELD_DECAY_KEEP_FRACTION,
    NEBULA_MINEFIELD_DECAY_KEEP_FRACTION,
    minefield_intersects_any_nebula,
    radius_from_units,
    remaining_units_after_decay,
    remaining_units_after_default_decay,
    remaining_units_after_nebula_decay,
)


@dataclass(frozen=True)
class _Nebula:
    id: int
    x: int
    y: int
    radius: int


def test_radius_from_units_uses_integer_sqrt() -> None:
    assert radius_from_units(0) == 0
    assert radius_from_units(-10) == 0
    assert radius_from_units(1) == 1
    assert radius_from_units(100) == 10
    assert radius_from_units(85) == 9
    assert radius_from_units(2308) == 48


def test_default_decay_keeps_95_percent_minus_one() -> None:
    assert remaining_units_after_default_decay(100) == 94
    assert remaining_units_after_default_decay(200) == 189
    assert remaining_units_after_default_decay(0) == 0
    assert remaining_units_after_default_decay(-5) == 0
    assert remaining_units_after_default_decay(1) == 0


def test_nebula_decay_keeps_85_percent_minus_one() -> None:
    assert remaining_units_after_nebula_decay(100) == 84
    assert remaining_units_after_nebula_decay(120) == 101
    assert remaining_units_after_nebula_decay(0) == 0
    assert remaining_units_after_nebula_decay(1) == 0


def test_remaining_units_after_decay_matches_keep_fraction_helpers() -> None:
    assert remaining_units_after_decay(100, DEFAULT_MINEFIELD_DECAY_KEEP_FRACTION) == 94
    assert remaining_units_after_decay(100, NEBULA_MINEFIELD_DECAY_KEEP_FRACTION) == 84


def test_nebula_overlap_true_when_disks_touch_at_edges() -> None:
    nebula = _Nebula(id=1, x=20, y=0, radius=10)
    assert minefield_intersects_any_nebula(0, 0, 10, (nebula,)) is True


def test_nebula_overlap_false_when_disks_do_not_touch() -> None:
    nebula = _Nebula(id=1, x=21, y=0, radius=10)
    assert minefield_intersects_any_nebula(0, 0, 10, (nebula,)) is False


def test_nebula_overlap_ignores_zero_radius_and_negative_id() -> None:
    colocated_zero = _Nebula(id=1, x=0, y=0, radius=0)
    negative_id = _Nebula(id=-1, x=0, y=0, radius=50)
    assert minefield_intersects_any_nebula(0, 0, 10, (colocated_zero, negative_id)) is False


def test_nebula_overlap_does_not_stack_multiple_hits() -> None:
    first = _Nebula(id=1, x=0, y=0, radius=5)
    second = _Nebula(id=2, x=0, y=0, radius=8)
    assert minefield_intersects_any_nebula(0, 0, 5, (first, second)) is True


def test_equal_pre_and_post_radius_from_units() -> None:
    units = 120
    pre_radius = radius_from_units(units)
    remaining = remaining_units_after_default_decay(units)
    assert pre_radius == 10
    assert remaining == 113
    assert radius_from_units(remaining) == pre_radius


def test_post_radius_zero_when_remaining_units_drop_to_zero() -> None:
    remaining = remaining_units_after_default_decay(1)
    assert remaining == 0
    assert radius_from_units(remaining) == 0

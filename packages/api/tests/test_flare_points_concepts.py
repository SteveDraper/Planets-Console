"""Unit tests for static flare-point tables and lookup."""

import api.concepts.flare_points as fp
from api.concepts.flare_points import FlareMovementKind, flare_points_for_warp
from api.models.flare_point import FlarePoint


def test_warp_one_and_two_have_no_flare_points():
    assert flare_points_for_warp(1, FlareMovementKind.REGULAR) == []
    assert flare_points_for_warp(2, FlareMovementKind.GRAVITONIC) == []


def test_quadrant_expansion_from_first_quadrant_seed():
    points = flare_points_for_warp(3, FlareMovementKind.REGULAR)
    assert len(points) == 4
    assert FlarePoint((13, 14), (7, 7), (6, 6)) in points
    assert FlarePoint((-13, 14), (-7, 7), (-6, 6)) in points
    assert FlarePoint((13, -14), (7, -7), (6, -6)) in points
    assert FlarePoint((-13, -14), (-7, -7), (-6, -6)) in points


def test_single_pair_seed_expands_to_identical_offsets():
    warp_five = flare_points_for_warp(5, FlareMovementKind.REGULAR)
    for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        wx, wy = sx * 16, sy * 20
        matches = [p for p in warp_five if p.waypoint_offset == (wx, wy)]
        assert len(matches) == 1
        p = matches[0]
        assert p.arrival_offset == (wx, wy) and p.direct_aim_arrival_offset == (wx, wy)


def test_expected_row_counts_after_quadrant_expansion():
    assert len(flare_points_for_warp(9, FlareMovementKind.REGULAR)) == 60
    assert len(flare_points_for_warp(9, FlareMovementKind.GRAVITONIC)) == 132


def test_tuple_rows_map_to_flare_point_dataclasses(monkeypatch):
    monkeypatch.setattr(
        fp,
        "FLARE_POINT_TUPLES_REGULAR_MOVEMENT",
        {9: [((10, 0), (12, 0), (11, 0))]},
    )
    got = flare_points_for_warp(9, FlareMovementKind.REGULAR)
    assert len(got) == 1
    p = got[0]
    assert p.waypoint_offset == (10, 0)
    assert p.arrival_offset == (12, 0)
    assert p.direct_aim_arrival_offset == (11, 0)


def test_gravitonic_table_is_separate_from_regular(monkeypatch):
    monkeypatch.setattr(
        fp,
        "FLARE_POINT_TUPLES_REGULAR_MOVEMENT",
        {5: [((1, 0), (2, 0), (1, 0))]},
    )
    monkeypatch.setattr(
        fp,
        "FLARE_POINT_TUPLES_GRAVITONIC_MOVEMENT",
        {5: [((3, 0), (4, 0), (3, 0))]},
    )
    regular = flare_points_for_warp(5, FlareMovementKind.REGULAR)
    grav = flare_points_for_warp(5, FlareMovementKind.GRAVITONIC)
    assert regular[0].waypoint_offset == (1, 0)
    assert grav[0].waypoint_offset == (3, 0)

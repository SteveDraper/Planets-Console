"""Static flare-point tables by warp speed and movement kind (regular vs gravitonic)."""

from enum import StrEnum

from api.concepts.flare_point_quadrant_seeds import (
    GRAVITONIC_FLARE_QUADRANT_I_SEEDS,
    REGULAR_FLARE_QUADRANT_I_SEEDS,
)
from api.models.flare_point import FlarePoint

_OffsetTriple = tuple[tuple[int, int], tuple[int, int], tuple[int, int]]

_QUADRANT_SIGNS: tuple[tuple[int, int], ...] = ((1, 1), (-1, 1), (1, -1), (-1, -1))


class FlareMovementKind(StrEnum):
    REGULAR = "regular"
    GRAVITONIC = "gravitonic"


def _pair(cell: list[int]) -> tuple[int, int]:
    if len(cell) != 2:
        msg = f"expected [x, y] pair, got length {len(cell)}"
        raise ValueError(msg)
    return (int(cell[0]), int(cell[1]))


def _normalize_quadrant_i_row(row: list[list[int]]) -> _OffsetTriple:
    """Normalize one seed row (1 or 3 pairs) to waypoint, arrival, and direct-aim offsets."""
    n = len(row)
    if n == 1:
        p = _pair(row[0])
        return (p, p, p)
    if n == 3:
        return (_pair(row[0]), _pair(row[1]), _pair(row[2]))
    msg = f"flare seed row must have 1 or 3 coordinate pairs, got {n}"
    raise ValueError(msg)


def _scale_triple(
    triple: _OffsetTriple,
    sx: int,
    sy: int,
) -> _OffsetTriple:
    def sc(p: tuple[int, int]) -> tuple[int, int]:
        return (sx * p[0], sy * p[1])

    return (sc(triple[0]), sc(triple[1]), sc(triple[2]))


def _expanded_tuple_rows_for_seeds(
    seeds: dict[int, list[list[list[int]]]],
) -> dict[int, list[_OffsetTriple]]:
    out: dict[int, list[_OffsetTriple]] = {}
    for warp_speed, rows in seeds.items():
        expanded: list[_OffsetTriple] = []
        for raw_row in rows:
            base = _normalize_quadrant_i_row(raw_row)
            for sx, sy in _QUADRANT_SIGNS:
                expanded.append(_scale_triple(base, sx, sy))
        out[warp_speed] = expanded
    return out


# Full tables (all quadrants), built from first-quadrant seeds.
FLARE_POINT_TUPLES_REGULAR_MOVEMENT: dict[int, list[_OffsetTriple]] = (
    _expanded_tuple_rows_for_seeds(REGULAR_FLARE_QUADRANT_I_SEEDS)
)

FLARE_POINT_TUPLES_GRAVITONIC_MOVEMENT: dict[int, list[_OffsetTriple]] = (
    _expanded_tuple_rows_for_seeds(GRAVITONIC_FLARE_QUADRANT_I_SEEDS)
)


def flare_points_for_warp(warp_speed: int, movement_kind: FlareMovementKind) -> list[FlarePoint]:
    """Return all flare points defined for ``warp_speed`` and ``movement_kind``."""
    table = (
        FLARE_POINT_TUPLES_GRAVITONIC_MOVEMENT
        if movement_kind is FlareMovementKind.GRAVITONIC
        else FLARE_POINT_TUPLES_REGULAR_MOVEMENT
    )
    raw = table.get(warp_speed, [])
    return [
        FlarePoint(
            waypoint_offset=t[0],
            arrival_offset=t[1],
            direct_aim_arrival_offset=t[2],
        )
        for t in raw
    ]

"""Flare point: waypoint trick that extends effective movement range at a given warp."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FlarePoint:
    """Relative offsets (dx, dy from the ship) for one flare geometry at a warp speed.

    ``waypoint_offset`` is the movement target (waypoint) the ship is ordered toward.
    ``arrival_offset`` is where the ship actually ends the move.
    ``direct_aim_arrival_offset`` is where the ship would end if it aimed straight at
    the arrival point instead (typically shorter than ``arrival_offset`` in range).
    """

    waypoint_offset: tuple[int, int]
    arrival_offset: tuple[int, int]
    direct_aim_arrival_offset: tuple[int, int]

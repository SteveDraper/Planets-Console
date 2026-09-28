"""Distinct league-team fills for the teams on one turn.

Hues are spaced around the wheel and given out so teams that share a border
stay as far apart as the team count allows. A border whose hues are still
close uses a different hatch.
"""

from __future__ import annotations

import colorsys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

LIGHTNESS = 0.64
SATURATION = 0.85
CLOSE_HUE_DEGREES = 60.0

FILL_PATTERNS = (
    "solid",
    "forward",
    "back",
    "horizontal",
    "vertical",
    "dots",
)


@dataclass(frozen=True)
class TeamStyle:
    fill_color: str
    fill_pattern: str


def _hue_distance(left: float, right: float) -> float:
    span = abs(left - right) % 360.0
    return min(span, 360.0 - span)


def fill_hex_for_hue(hue: float) -> str:
    red, green, blue = colorsys.hls_to_rgb(hue / 360.0, LIGHTNESS, SATURATION)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def _border_score(
    hue: float,
    *,
    team_id: int,
    assigned_hue: dict[int, float],
    neighbors: Mapping[int, set[int]],
) -> tuple[float, float]:
    pool = [
        assigned_hue[neighbor]
        for neighbor in neighbors.get(team_id, ())
        if neighbor in assigned_hue
    ]
    if not pool:
        pool = list(assigned_hue.values())
    distance = 360.0 if not pool else min(_hue_distance(hue, other) for other in pool)
    return (distance, -hue)


def assign_team_styles(
    team_ids: Iterable[int],
    neighbors: Mapping[int, set[int]],
) -> dict[int, TeamStyle]:
    """One style per league team. ``neighbors`` lists teams that share a border."""
    ids = sorted({team_id for team_id in team_ids if team_id > 0})
    count = len(ids)
    if count == 0:
        return {}
    hues = [index * (360.0 / count) for index in range(count)]
    assigned_hue: dict[int, float] = {}
    remaining = list(range(count))
    for team_id in ids:
        chosen = max(
            remaining,
            key=lambda index, team_id=team_id: _border_score(
                hues[index],
                team_id=team_id,
                assigned_hue=assigned_hue,
                neighbors=neighbors,
            ),
        )
        remaining.remove(chosen)
        assigned_hue[team_id] = hues[chosen]

    assigned_pattern: dict[int, str] = {}
    for team_id in ids:
        blocked = {
            assigned_pattern[neighbor]
            for neighbor in neighbors.get(team_id, ())
            if neighbor in assigned_pattern
            and _hue_distance(assigned_hue[team_id], assigned_hue[neighbor]) < CLOSE_HUE_DEGREES
        }
        pattern = next((item for item in FILL_PATTERNS if item not in blocked), None)
        if pattern is None:
            pattern = min(
                FILL_PATTERNS,
                key=lambda item: (
                    sum(
                        1
                        for neighbor in neighbors.get(team_id, ())
                        if assigned_pattern.get(neighbor) == item
                        and _hue_distance(assigned_hue[team_id], assigned_hue[neighbor])
                        < CLOSE_HUE_DEGREES
                    ),
                    FILL_PATTERNS.index(item),
                ),
            )
        assigned_pattern[team_id] = pattern

    return {
        team_id: TeamStyle(
            fill_color=fill_hex_for_hue(assigned_hue[team_id]),
            fill_pattern=assigned_pattern[team_id],
        )
        for team_id in ids
    }

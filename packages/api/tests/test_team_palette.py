"""League-team fill assignment: distinct hues, hatch when a border is still close."""

from itertools import combinations

from api.analytics.team_palette import (
    CLOSE_HUE_DEGREES,
    FILL_PATTERNS,
    assign_team_styles,
    fill_hex_for_hue,
)


def _hue_of(color: str, count: int) -> float:
    for index in range(count):
        hue = index * (360.0 / count)
        if fill_hex_for_hue(hue) == color:
            return hue
    raise AssertionError(color)


def _hue_distance(left: float, right: float) -> float:
    span = abs(left - right) % 360.0
    return min(span, 360.0 - span)


def test_two_bordering_teams_sit_opposite_on_the_wheel() -> None:
    styles = assign_team_styles([8, 4], {4: {8}, 8: {4}})
    assert styles[4].fill_color == fill_hex_for_hue(0)
    assert styles[8].fill_color == fill_hex_for_hue(180)
    assert styles[4].fill_pattern == "solid"
    assert styles[8].fill_pattern == "solid"


def test_close_border_hues_use_different_hatches() -> None:
    """Bundy Sector team ids, including 149 and 413, which share a border there."""
    team_ids = [9, 49, 65, 66, 67, 70, 71, 76, 124, 144, 149, 174, 233, 284, 413, 427]
    neighbors = {team_id: set(team_ids) - {team_id} for team_id in team_ids}
    styles = assign_team_styles(team_ids, neighbors)
    assert len({style.fill_color for style in styles.values()}) == len(team_ids)
    assert styles[149].fill_color != styles[413].fill_color
    assert styles[149].fill_pattern in FILL_PATTERNS
    for left, right in combinations(team_ids, 2):
        distance = _hue_distance(
            _hue_of(styles[left].fill_color, len(team_ids)),
            _hue_of(styles[right].fill_color, len(team_ids)),
        )
        if distance < CLOSE_HUE_DEGREES:
            assert styles[left].fill_pattern != styles[right].fill_pattern

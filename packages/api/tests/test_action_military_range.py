"""Count-interval military envelopes for candidate actions."""

from api.analytics.military_score_inference.models import (
    CandidateAction,
    action_military_range_2x,
)


def test_negative_score_range_is_the_endpoint_envelope() -> None:
    action = CandidateAction(
        id="loss",
        label="loss",
        score_delta_2x=-12,
        lower_bound=1,
        upper_bound=4,
    )
    assert action_military_range_2x(action) == (-48, -12)


def test_negative_interval_widens_toward_the_higher_count() -> None:
    action = CandidateAction(
        id="span",
        label="span",
        score_delta_2x=0,
        lower_bound=0,
        upper_bound=3,
        score_delta_2x_min=-5,
        score_delta_2x_max=2,
    )
    assert action_military_range_2x(action) == (-15, 6)


def test_inverted_count_bounds_contribute_nothing() -> None:
    action = CandidateAction(
        id="empty",
        label="empty",
        score_delta_2x=-12,
        lower_bound=3,
        upper_bound=1,
    )
    assert action_military_range_2x(action) == (0, 0)

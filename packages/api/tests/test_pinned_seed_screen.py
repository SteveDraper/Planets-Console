"""Band-retry skip when a negative military ceiling cannot be reached."""

from api.analytics.military_score_inference.models import (
    CandidateAction,
    InferenceObservation,
    ShipBuildCombo,
)
from api.analytics.military_score_inference.pinned_seed_screen import (
    negative_band_upper_bound_is_unreachable,
)


def _observation(
    *,
    military_delta_2x: int,
    warship_delta: int = 0,
    freighter_delta: int = 0,
) -> InferenceObservation:
    return InferenceObservation(
        player_id=1,
        turn=15,
        military_delta_2x=military_delta_2x,
        warship_delta=warship_delta,
        freighter_delta=freighter_delta,
        priority_point_delta=0,
        starbases_owned=1,
        is_after_ship_limit=False,
        military_partition_slack_2x=0,
    )


def test_negative_ceiling_is_unreachable_without_a_usable_negative_action() -> None:
    loss = CandidateAction(
        id="ship_loss:warship:point:8312",
        label="Lost warship",
        score_delta_2x=-8312,
        warship_delta=-1,
        upper_bound=1,
    )
    posts = CandidateAction(
        id="planet_defense_posts_added_total",
        label="Planet defense",
        score_delta_2x=11,
        upper_bound=16,
    )
    observation = _observation(military_delta_2x=-3250)
    assert negative_band_upper_bound_is_unreachable(observation, (loss, posts))


def test_negative_ceiling_stays_reachable_when_a_departure_is_legal() -> None:
    loss = CandidateAction(
        id="ship_loss:warship:point:120",
        label="Lost warship",
        score_delta_2x=-120,
        warship_delta=-1,
        upper_bound=1,
    )
    observation = _observation(military_delta_2x=-100, warship_delta=-1)
    assert not negative_band_upper_bound_is_unreachable(observation, (loss,))


def test_negative_ceiling_stays_reachable_when_a_build_offsets_the_loss() -> None:
    loss = CandidateAction(
        id="ship_loss:warship:point:8312",
        label="Lost warship",
        score_delta_2x=-8312,
        warship_delta=-1,
        upper_bound=1,
    )
    build = ShipBuildCombo(
        combo_id="combo_warship",
        hull_id=1,
        engine_id=1,
        beam_id=None,
        torp_id=None,
        beam_count=0,
        launcher_count=0,
        labels=("Warship",),
        score_delta_2x=400,
        warship_delta=1,
        upper_bound=1,
    )
    observation = _observation(military_delta_2x=-3250)
    assert not negative_band_upper_bound_is_unreachable(observation, (loss,), (build,))


def test_negative_score_without_a_class_change_keeps_the_band_search() -> None:
    transfer = CandidateAction(
        id="fighters_ship_to_starbase",
        label="Fighters ship to SB",
        score_delta_2x=-10,
        upper_bound=4,
    )
    observation = _observation(military_delta_2x=-8)
    assert not negative_band_upper_bound_is_unreachable(observation, (transfer,))


def test_non_negative_ceiling_still_runs_the_band_search() -> None:
    posts = CandidateAction(
        id="planet_defense_posts_added_total",
        label="Planet defense",
        score_delta_2x=11,
        upper_bound=16,
    )
    observation = _observation(military_delta_2x=40)
    assert not negative_band_upper_bound_is_unreachable(observation, (posts,))

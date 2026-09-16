"""Unique-fill persist does not open next-turn ship-build catalog width (#487).

A singleton option set unique-fills and is a decrease candidate, but it is not
a departure pin. Extra warship replacement capacity requires known spec.
A multi-hull fan without envelopes is still not a candidate. Envelope-only
fans remain candidates but do not open extra-warship capacity.
"""

from api.analytics.military_score_inference.prior_fleet_decrease_candidates import (
    decrease_capacity_by_class,
    prior_fleet_decrease_candidates,
)
from api.analytics.military_score_inference.ship_build_combos import (
    GENERIC_FREIGHTER_COMBO_ID,
    generate_ship_build_combos,
    ship_build_upper_bound,
)
from api.analytics.military_score_inference.ship_transfer_families import (
    build_ship_transfer_catalog_fragment,
)
from api.concepts.ship_build_military import ship_build_military_score_delta_2x

from tests.fixtures.military_score_inference import _observation
from tests.fixtures.ship_transfer_families import (
    _enveloped_multi_hull_unknown_warship,
    _known_warship_record,
    _multi_hull_unknown_warship,
    _singleton_unknown_hull_warship,
    _transfer_catalog_kwargs,
)


def _singleton_fill_military_2x(synthetic_catalog_context) -> int:
    return ship_build_military_score_delta_2x(
        synthetic_catalog_context["hulls_by_id"][24],
        synthetic_catalog_context["engines_by_id"][1],
        synthetic_catalog_context["beams_by_id"][1],
        None,
        beam_count=2,
        launcher_count=0,
    )


def _net_zero_observation(*, military_delta_2x: int):
    return _observation(
        military_delta_2x=military_delta_2x,
        warship_delta=0,
        freighter_delta=0,
        starbases_owned=1,
    )


def _fragment_for(synthetic_catalog_context, record, observation):
    return build_ship_transfer_catalog_fragment(
        observation,
        peer_rows=(),
        prior_fleet_records=(record,),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )


def _warship_combo_ids(combos) -> frozenset[str]:
    return frozenset(
        combo.combo_id
        for combo in combos
        if combo.warship_delta == 1 and combo.combo_id != GENERIC_FREIGHTER_COMBO_ID
    )


def test_singleton_unknown_hull_is_point_warship_decrease_candidate(
    synthetic_catalog_context,
):
    military_2x = _singleton_fill_military_2x(synthetic_catalog_context)
    candidates = prior_fleet_decrease_candidates(
        (_singleton_unknown_hull_warship(),),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    assert len(candidates) == 1
    assert candidates[0].ship_class == "warship"
    assert candidates[0].is_point_military is True
    assert candidates[0].score_delta_2x_min == military_2x
    assert candidates[0].score_delta_2x_max == military_2x
    assert decrease_capacity_by_class(candidates) == (1, 0)


def test_multi_hull_fan_without_envelopes_is_not_a_decrease_candidate(
    synthetic_catalog_context,
):
    candidates = prior_fleet_decrease_candidates(
        (_multi_hull_unknown_warship(),),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    assert candidates == ()
    assert decrease_capacity_by_class(candidates) == (0, 0)


def test_enveloped_multi_hull_fan_is_interval_decrease_candidate(
    synthetic_catalog_context,
):
    candidates = prior_fleet_decrease_candidates(
        (_enveloped_multi_hull_unknown_warship(),),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    assert len(candidates) == 1
    assert candidates[0].ship_class == "warship"
    assert candidates[0].is_point_military is False
    assert candidates[0].score_delta_2x_min == 20
    assert candidates[0].score_delta_2x_max == 80
    assert decrease_capacity_by_class(candidates) == (1, 0)


def test_unique_fill_does_not_open_net_zero_warship_catalog(
    synthetic_catalog_context,
):
    military_2x = _singleton_fill_military_2x(synthetic_catalog_context)
    observation = _net_zero_observation(military_delta_2x=military_2x)
    known, _ = _known_warship_record(synthetic_catalog_context)

    singleton = _fragment_for(
        synthetic_catalog_context, _singleton_unknown_hull_warship(), observation
    )
    fan = _fragment_for(synthetic_catalog_context, _multi_hull_unknown_warship(), observation)
    enveloped = _fragment_for(
        synthetic_catalog_context, _enveloped_multi_hull_unknown_warship(), observation
    )
    pinned = _fragment_for(synthetic_catalog_context, known, observation)

    assert singleton.prior_warship_departure_cap == 1
    assert singleton.extra_warship_capacity == 0
    assert fan.prior_warship_departure_cap == 0
    assert fan.extra_warship_capacity == 0
    assert enveloped.prior_warship_departure_cap == 1
    assert enveloped.extra_warship_capacity == 0
    assert pinned.extra_warship_capacity == 1

    assert (
        ship_build_upper_bound(
            observation,
            is_warship=True,
            is_freighter=False,
            extra_warship_capacity=singleton.extra_warship_capacity,
        )
        == 0
    )
    assert (
        ship_build_upper_bound(
            observation,
            is_warship=True,
            is_freighter=False,
            extra_warship_capacity=fan.extra_warship_capacity,
        )
        == 0
    )
    assert (
        ship_build_upper_bound(
            observation,
            is_warship=True,
            is_freighter=False,
            extra_warship_capacity=pinned.extra_warship_capacity,
        )
        == 1
    )

    singleton_combos = generate_ship_build_combos(
        observation,
        **synthetic_catalog_context,
        extra_warship_capacity=singleton.extra_warship_capacity,
        extra_freighter_capacity=singleton.extra_freighter_capacity,
    )
    fan_combos = generate_ship_build_combos(
        observation,
        **synthetic_catalog_context,
        extra_warship_capacity=fan.extra_warship_capacity,
        extra_freighter_capacity=fan.extra_freighter_capacity,
    )
    enveloped_combos = generate_ship_build_combos(
        observation,
        **synthetic_catalog_context,
        extra_warship_capacity=enveloped.extra_warship_capacity,
        extra_freighter_capacity=enveloped.extra_freighter_capacity,
    )

    assert _warship_combo_ids(singleton_combos) == frozenset()
    assert _warship_combo_ids(fan_combos) == frozenset()
    assert not any(combo.combo_id == GENERIC_FREIGHTER_COMBO_ID for combo in fan_combos)
    assert _warship_combo_ids(enveloped_combos) == frozenset()

"""Prior-fleet decrease candidate derivation for ship transfer families (#370)."""

from api.analytics.military_score_inference.prior_fleet_decrease_candidates import (
    prior_fleet_decrease_candidates,
)

from tests.fixtures.ship_transfer_families import (
    _class_only_freighter_record,
    _class_only_warship_record,
    _envelope_warship_record,
    _known_warship_record,
    _transfer_catalog_kwargs,
    _unknown_hull_envelope_warship_record,
)


def test_known_hull_candidate_is_point_military(synthetic_catalog_context):
    record, military_2x = _known_warship_record(synthetic_catalog_context)
    candidates = prior_fleet_decrease_candidates(
        (record,),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    assert len(candidates) == 1
    assert candidates[0].is_point_military is True
    assert candidates[0].score_delta_2x_min == military_2x
    assert candidates[0].score_delta_2x_max == military_2x
    assert candidates[0].ship_class == "warship"


def test_option_set_envelope_candidate_is_interval(synthetic_catalog_context):
    candidates = prior_fleet_decrease_candidates(
        (_envelope_warship_record(),),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    assert len(candidates) == 1
    assert candidates[0].is_point_military is False
    assert candidates[0].score_delta_2x_min == 20
    assert candidates[0].score_delta_2x_max == 80


def test_class_only_warship_without_envelope_is_not_a_candidate(synthetic_catalog_context):
    candidates = prior_fleet_decrease_candidates(
        (_class_only_warship_record(),),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    assert candidates == ()


def test_unknown_hull_warship_with_record_envelope_is_candidate(synthetic_catalog_context):
    candidates = prior_fleet_decrease_candidates(
        (_unknown_hull_envelope_warship_record(),),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    assert len(candidates) == 1
    assert candidates[0].is_point_military is False
    assert candidates[0].score_delta_2x_min == 20
    assert candidates[0].score_delta_2x_max == 80
    assert candidates[0].ship_class == "warship"


def test_class_only_freighter_is_zero_military(synthetic_catalog_context):
    candidates = prior_fleet_decrease_candidates(
        (_class_only_freighter_record(),),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    assert len(candidates) == 1
    assert candidates[0].ship_class == "freighter"
    assert candidates[0].score_delta_2x_min == 0
    assert candidates[0].score_delta_2x_max == 0


def test_inactive_records_are_not_decrease_candidates(synthetic_catalog_context):
    record, _ = _known_warship_record(synthetic_catalog_context)
    record.disposition = "lost"
    candidates = prior_fleet_decrease_candidates(
        (record,),
        **_transfer_catalog_kwargs(synthetic_catalog_context),
    )
    assert candidates == ()

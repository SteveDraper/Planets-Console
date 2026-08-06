"""Tests for wire-only fleet ship military estimates."""

from __future__ import annotations

from api.analytics.fleet.military_estimate import (
    fleet_ship_military_estimate_2x,
    resolve_display_default_build_option_set,
)
from api.analytics.fleet.serialization import fleet_ship_record_to_json
from api.analytics.fleet.table_wire import fleet_ship_record_to_table_wire
from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetShipRecord,
    FleetShipRecordFields,
)
from api.analytics.military_score_inference.ship_build_scoring import (
    default_build_components,
    ship_build_military_score_delta_2x,
)
from api.concepts.turn_component_catalog import (
    beams_by_id,
    engines_by_id,
    hulls_by_id,
    torpedos_by_id,
)


def _serpent_record(
    *,
    beam_id: int | None = None,
    beam_count: int | None = None,
    engine_id: int | None = 9,
    display_index: int | None = 0,
    extra_option_sets: list[FleetBuildOptionSet] | None = None,
) -> FleetShipRecord:
    option_set = FleetBuildOptionSet(
        combo_id="combo_serpent",
        label="Serpent",
        solution_rank_weight=10,
        hull_id=24,
        engine_id=engine_id,
        beam_id=beam_id,
        beam_count=beam_count,
        launcher_count=0,
    )
    option_sets = [option_set, *(extra_option_sets or [])]
    return FleetShipRecord(
        record_id="rec-serpent",
        disposition="active",
        fields=FleetShipRecordFields(
            hull=FleetFieldKnown(24),
            engine=FleetFieldKnown(engine_id) if engine_id else FleetFieldUnknown(),
            beams=FleetFieldKnown(beam_id) if beam_id else FleetFieldUnknown(),
            launchers=FleetFieldKnown(0),
        ),
        build_option_sets=option_sets,
        display_default_option_set_index=display_index,
    )


def test_resolve_display_default_prefers_explicit_index():
    low = FleetBuildOptionSet(combo_id="low", solution_rank_weight=1, hull_id=24)
    high = FleetBuildOptionSet(combo_id="high", solution_rank_weight=99, hull_id=1)
    record = FleetShipRecord(
        record_id="r",
        build_option_sets=[low, high],
        display_default_option_set_index=0,
    )
    assert resolve_display_default_build_option_set(record) is low


def test_resolve_display_default_falls_back_to_highest_weight():
    low = FleetBuildOptionSet(combo_id="low", solution_rank_weight=1, hull_id=24)
    high = FleetBuildOptionSet(combo_id="high", solution_rank_weight=99, hull_id=1)
    record = FleetShipRecord(record_id="r", build_option_sets=[low, high])
    assert resolve_display_default_build_option_set(record) is high


def test_estimate_uses_known_parts_via_shared_scorer(sample_turn):
    record = _serpent_record(beam_id=3, beam_count=2, engine_id=1)
    estimate = fleet_ship_military_estimate_2x(record, turn=sample_turn)
    hull = hulls_by_id(sample_turn)[24]
    engine = engines_by_id(sample_turn)[1]
    beam = beams_by_id(sample_turn)[3]
    expected = ship_build_military_score_delta_2x(
        hull,
        engine,
        beam,
        None,
        beam_count=2,
        launcher_count=0,
    )
    assert estimate == expected
    assert estimate > 0


def test_estimate_fills_unknown_beams_full_at_default_components(sample_turn):
    record = _serpent_record(beam_id=None, beam_count=None, engine_id=None)
    record.fields.engine = FleetFieldUnknown()
    record.fields.beams = FleetFieldUnknown()
    record.build_option_sets[0] = FleetBuildOptionSet(
        combo_id="combo_serpent",
        hull_id=24,
        engine_id=None,
        beam_id=None,
        beam_count=None,
        launcher_count=0,
    )
    estimate = fleet_ship_military_estimate_2x(record, turn=sample_turn)
    hull = hulls_by_id(sample_turn)[24]
    defaults = default_build_components(
        engines_by_id=engines_by_id(sample_turn),
        beams_by_id=beams_by_id(sample_turn),
        torpedos_by_id=torpedos_by_id(sample_turn),
    )
    assert defaults.engine is not None
    assert defaults.beam is not None
    expected = ship_build_military_score_delta_2x(
        hull,
        defaults.engine,
        defaults.beam,
        None,
        beam_count=hull.beams,
        launcher_count=0,
    )
    assert estimate == expected


def test_estimate_known_zero_beams_scores_zero_for_non_fighter_hull(sample_turn):
    record = _serpent_record(beam_id=None, beam_count=0, engine_id=1)
    record.fields.beams = FleetFieldKnown(0)
    estimate = fleet_ship_military_estimate_2x(record, turn=sample_turn)
    assert estimate == 0


def test_estimate_generic_freighter_is_zero(sample_turn):
    record = FleetShipRecord(
        record_id="rec-freight",
        build_option_sets=[
            FleetBuildOptionSet(
                combo_id="combo_freighter",
                label="Freighter",
                hull_id=0,
                beam_count=0,
                launcher_count=0,
            )
        ],
        display_default_option_set_index=0,
    )
    assert fleet_ship_military_estimate_2x(record, turn=sample_turn) == 0


def test_estimate_catalog_freighter_is_zero(sample_turn):
    record = FleetShipRecord(
        record_id="rec-sdsf",
        fields=FleetShipRecordFields(hull=FleetFieldKnown(15)),
        build_option_sets=[
            FleetBuildOptionSet(
                combo_id="combo_15",
                hull_id=15,
                engine_id=1,
                beam_count=0,
                launcher_count=0,
            )
        ],
        display_default_option_set_index=0,
    )
    assert fleet_ship_military_estimate_2x(record, turn=sample_turn) == 0


def test_estimate_omitted_when_hull_unknown(sample_turn):
    record = FleetShipRecord(record_id="rec-unknown")
    assert fleet_ship_military_estimate_2x(record, turn=sample_turn) is None


def test_table_wire_attaches_estimate_when_turn_provided(sample_turn):
    record = _serpent_record(beam_id=1, beam_count=2, engine_id=1)
    durable = fleet_ship_record_to_json(record)
    assert "militaryEstimate2x" not in durable

    without_turn = fleet_ship_record_to_table_wire(record)
    assert "militaryEstimate2x" not in without_turn

    with_turn = fleet_ship_record_to_table_wire(record, turn=sample_turn)
    assert with_turn["militaryEstimate2x"] == fleet_ship_military_estimate_2x(
        record, turn=sample_turn
    )


def test_table_wire_omits_estimate_when_not_estimable(sample_turn):
    record = FleetShipRecord(record_id="rec-unknown")
    wire = fleet_ship_record_to_table_wire(record, turn=sample_turn)
    assert "militaryEstimate2x" not in wire
    assert "events" not in wire

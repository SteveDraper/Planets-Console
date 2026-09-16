"""Count-lattice signal and departure pin (#486)."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetFieldKnown,
    FleetFieldUnknown,
    FleetShipRecord,
    FleetShipRecordFields,
)
from api.analytics.military_score_inference.count_lattice import (
    CountLatticeClassEvent,
    DeparturePin,
    _remainder_sets_after_alibi,
    class_drops_from_observation,
    count_lattice_signal,
    departure_pin,
    record_has_known_spec,
)
from api.analytics.military_score_inference.models import InferenceObservation
from api.analytics.military_score_inference.public_scoreboard_pairing import (
    PublicScoreboardRow,
    classify_public_scoreboard_pairing,
    public_scoreboard_row_from_observation,
    transfer_budget_for_row,
)
from api.models.ship import Ship

from tests.fixtures.military_score_inference import _observation
from tests.fixtures.pp_gap_transfer import birds_row
from tests.fixtures.ship_transfer_families import (
    _known_warship_record,
    _multi_hull_unknown_warship,
    _scoreboard_class_event,
    _singleton_unknown_hull_warship,
)

DIAMOND_FLAME_HULL_ID = 63
PLAYER_ID = 8


def _signal(observation, *, peer_rows=(), settings=None):
    row = public_scoreboard_row_from_observation(observation)
    pairing = classify_public_scoreboard_pairing(
        row,
        peer_rows,
        settings=settings,
        is_after_ship_limit=observation.is_after_ship_limit,
    )
    idle_dock = transfer_budget_for_row(
        row,
        settings=settings,
        is_after_ship_limit=observation.is_after_ship_limit,
    )
    return count_lattice_signal(observation, pairing, idle_dock)


def _ledger(*records: FleetShipRecord) -> FleetAcquisitionLedger:
    return FleetAcquisitionLedger(player_id=PLAYER_ID, records=list(records))


def _known_spec_warship(
    *,
    record_id: str,
    hull_id: int = 24,
    ship_id: int | None = None,
    engine_id: int = 1,
    beam_id: int = 1,
    launcher_id: int = 0,
) -> FleetShipRecord:
    return FleetShipRecord(
        record_id=record_id,
        fields=FleetShipRecordFields(
            ship_id=FleetFieldKnown(ship_id) if ship_id is not None else FleetFieldUnknown(),
            hull=FleetFieldKnown(hull_id),
            engine=FleetFieldKnown(engine_id),
            beams=FleetFieldKnown(beam_id),
            launchers=FleetFieldKnown(launcher_id),
        ),
        events=[_scoreboard_class_event("warship")],
    )


def _viewpoint_ship(*, ship_id: int, ownerid: int = PLAYER_ID, hullid: int = 24) -> Ship:
    return Ship(
        id=ship_id,
        friendlycode="aaa",
        name=f"S{ship_id}",
        warp=0,
        x=0,
        y=0,
        beams=0,
        bays=0,
        torps=0,
        mission=0,
        mission1target=0,
        mission2target=0,
        enemy=0,
        damage=0,
        crew=0,
        clans=0,
        neutronium=0,
        tritanium=0,
        duranium=0,
        molybdenum=0,
        supplies=0,
        ammo=0,
        megacredits=0,
        transferclans=0,
        transferneutronium=0,
        transferduranium=0,
        transfertritanium=0,
        transfermolybdenum=0,
        transfersupplies=0,
        transferammo=0,
        transfermegacredits=0,
        transfertargetid=0,
        transfertargettype=0,
        targetx=0,
        targety=0,
        mass=100,
        heading=0,
        turn=1,
        turnkilled=0,
        beamid=0,
        engineid=1,
        hullid=hullid,
        ownerid=ownerid,
        torpedoid=0,
        experience=0,
        infoturn=1,
        podhullid=0,
        podcargo=0,
        goal=0,
        goaltarget=0,
        goaltarget2=0,
    )


def _pin(
    observation,
    records: tuple[FleetShipRecord, ...],
    this_turn_ships: tuple[Ship, ...] = (),
    *,
    hulls_by_id,
) -> tuple[DeparturePin, ...]:
    return departure_pin(
        observation,
        _ledger(*records),
        this_turn_ships,
        hulls_by_id=hulls_by_id,
    )


def test_quiet_warship_delta_zero_unique_fill_is_not_count_lattice_signal():
    """A last-turn unique-fill persist is not a count-lattice source."""
    assert _singleton_unknown_hull_warship().build_option_sets
    observation = _observation(warship_delta=0, freighter_delta=0, military_delta_2x=0)
    signal = _signal(observation)
    assert not signal
    assert signal.events == ()


def test_unmatched_warship_drop_is_count_lattice_signal():
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    signal = _signal(observation)
    assert signal
    assert (
        CountLatticeClassEvent(
            ship_class="warship",
            source="unmatched_drop",
            count=1,
        )
        in signal.events
    )


def test_gift_pairing_is_count_lattice_signal():
    observation = _observation(warship_delta=-1, freighter_delta=0, military_delta_2x=-40)
    peer = PublicScoreboardRow(
        player_id=3,
        warship_delta=1,
        freighter_delta=0,
        military_delta_2x=40,
    )
    signal = _signal(observation, peer_rows=(peer,))
    assert signal
    assert any(
        event.source == "pairing" and event.ship_class == "warship" for event in signal.events
    )
    assert not any(event.source == "unmatched_drop" for event in signal.events)


def test_idle_dock_hidden_departure_is_count_lattice_signal(sample_turn):
    row = birds_row()
    observation = InferenceObservation(
        player_id=row.player_id,
        turn=15,
        military_delta_2x=row.military_delta_2x,
        warship_delta=row.warship_delta,
        freighter_delta=row.freighter_delta,
        priority_point_delta=row.priority_point_delta,
        starbases_owned=row.starbases,
        is_after_ship_limit=False,
        planet_delta=row.planet_delta,
        starbase_delta=row.starbase_delta,
    )
    signal = _signal(observation, settings=sample_turn.settings)
    assert signal
    assert any(event.source == "idle_dock" and event.count == 1 for event in signal.events)


def test_visible_idle_dock_build_without_departure_is_not_count_lattice_signal(sample_turn):
    observation = _observation(
        warship_delta=1,
        freighter_delta=0,
        military_delta_2x=40,
        starbases_owned=1,
    )
    observation = replace(observation, priority_point_delta=0)
    signal = _signal(observation, settings=sample_turn.settings)
    assert not signal


def test_rst_known_single_remainder_is_exact_set_pin(synthetic_catalog_context):
    record, _ = _known_warship_record(synthetic_catalog_context)
    assert record_has_known_spec(record) is True
    pins = _pin(
        _observation(warship_delta=-1, military_delta_2x=-40),
        (record,),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert pins == (
        DeparturePin(kind="exact_set", ship_class="warship", record_ids=(record.record_id,)),
    )


def test_still_owned_known_ship_id_is_alibied(synthetic_catalog_context):
    kept = _known_spec_warship(record_id="kept", ship_id=20)
    seen = _known_spec_warship(record_id="seen", ship_id=10)
    pins = _pin(
        _observation(warship_delta=-1, military_delta_2x=-40),
        (seen, kept),
        (_viewpoint_ship(ship_id=10),),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert pins == (DeparturePin(kind="exact_set", ship_class="warship", record_ids=("kept",)),)


def test_two_remaining_mixed_hulls_with_drop_two_are_exact_set_pin(synthetic_catalog_context):
    serpent = _known_spec_warship(record_id="serpent", hull_id=24)
    carrier = _known_spec_warship(record_id="carrier", hull_id=71, beam_id=0)
    pins = _pin(
        _observation(warship_delta=-2, military_delta_2x=-80),
        (serpent, carrier),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert pins == (
        DeparturePin(
            kind="exact_set",
            ship_class="warship",
            record_ids=("serpent", "carrier"),
        ),
    )


def test_ten_identical_known_diamond_flames_drop_one_is_spec_only_pin(
    synthetic_catalog_context,
):
    records = tuple(
        _known_spec_warship(
            record_id=f"flame-{index}",
            hull_id=DIAMOND_FLAME_HULL_ID,
            ship_id=100 + index,
        )
        for index in range(10)
    )
    pins = _pin(
        _observation(warship_delta=-1, military_delta_2x=-40),
        records,
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert pins == (DeparturePin(kind="spec_only", ship_class="warship", record_ids=()),)


def test_zero_drop_class_is_omitted_not_fail(synthetic_catalog_context):
    record, _ = _known_warship_record(synthetic_catalog_context)
    pins = _pin(
        _observation(warship_delta=0, military_delta_2x=0),
        (record,),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert pins == ()


def test_ten_mixed_known_hulls_drop_one_fails(synthetic_catalog_context):
    records = tuple(
        _known_spec_warship(
            record_id=f"mixed-{index}",
            hull_id=24 if index < 5 else 71,
            beam_id=1 if index < 5 else 0,
        )
        for index in range(10)
    )
    pins = _pin(
        _observation(warship_delta=-1, military_delta_2x=-40),
        records,
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert pins == (DeparturePin(kind="fail", ship_class="warship", record_ids=()),)


def test_known_spec_plus_unique_fill_sibling_fails(synthetic_catalog_context):
    known, _ = _known_warship_record(synthetic_catalog_context)
    pins = _pin(
        _observation(warship_delta=-1, military_delta_2x=-40),
        (known, _singleton_unknown_hull_warship()),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert pins == (DeparturePin(kind="fail", ship_class="warship", record_ids=()),)


def test_last_turn_inference_singleton_option_set_is_not_known_spec(
    synthetic_catalog_context,
):
    unique_fill = _singleton_unknown_hull_warship()
    assert record_has_known_spec(unique_fill) is False
    pins = _pin(
        _observation(warship_delta=-1, military_delta_2x=-40),
        (unique_fill,),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert pins == (DeparturePin(kind="fail", ship_class="warship", record_ids=()),)


def test_unid_inferred_row_cannot_be_alibied_by_hull_only_sighting(
    synthetic_catalog_context,
):
    inferred = _multi_hull_unknown_warship()
    pins = _pin(
        _observation(warship_delta=-1, military_delta_2x=-40),
        (inferred,),
        (_viewpoint_ship(ship_id=99, hullid=24),),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert pins == (DeparturePin(kind="fail", ship_class="warship", record_ids=()),)


def test_unique_option_hull_id_cannot_unique_fill_into_a_pin(synthetic_catalog_context):
    unique_fill = _singleton_unknown_hull_warship()
    assert unique_fill.build_option_sets[0].hull_id == 24
    pins = _pin(
        _observation(warship_delta=-1, military_delta_2x=-40),
        (unique_fill,),
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    assert pins == (DeparturePin(kind="fail", ship_class="warship", record_ids=()),)


def test_class_drops_from_observation_are_scoreboard_column_losses():
    drops = class_drops_from_observation(
        _observation(warship_delta=-2, freighter_delta=1, military_delta_2x=-80)
    )
    assert drops == {"warship": 2, "freighter": 0}


def test_remainder_sets_honor_injected_class_drops(synthetic_catalog_context):
    record, _ = _known_warship_record(synthetic_catalog_context)
    remainder_sets = _remainder_sets_after_alibi(
        PLAYER_ID,
        _ledger(record),
        (),
        {"warship": 2, "freighter": 0},
        hulls_by_id=synthetic_catalog_context["hulls_by_id"],
    )
    by_class = {item.ship_class: item for item in remainder_sets}
    assert by_class["warship"].drop == 2
    assert by_class["warship"].remainders == (record,)
    assert by_class["freighter"].drop == 0

"""Fleet@T retires exact-set pinned departures and does not ingest placeholders (#490)."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.fleet.chain import apply_fleet_turn_delta, ensure_fleet_baseline
from api.analytics.fleet.held_solutions import FleetInferenceMaterialization, FleetInferenceSupport
from api.analytics.fleet.types import (
    FleetBuildOptionSet,
    FleetFieldKnown,
    FleetShipRecord,
    FleetShipRecordFields,
)
from api.analytics.military_score_inference.post_unsat_placeholders import (
    UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID,
)
from api.analytics.military_score_inference.solver import STATUS_EXACT, STATUS_MODERATE_RESIDUAL
from api.analytics.military_score_inference.uncharacterized_roster import (
    STATUS_UNCHARACTERIZED_ROSTER,
)
from api.analytics.military_score_inference.uncharacterized_roster_types import (
    ExactSetDeparturePin,
    ExactSetPinRecord,
    PlaceholderDeparture,
)
from api.analytics.scores.export_services import ScoresExportContext
from api.concepts.hulls import UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.serialization.uncharacterized_roster import (
    PLACEHOLDER_DEPARTURE_ID,
    departure_pins_to_json,
    placeholder_departure_to_json,
)
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.fleet_fixtures import ledger_for_player, single_ship_turn

_GAME_ID = 628580
_PERSPECTIVE = 1
_OWNER_ID = 8
_HOST_TURN = 111
_ENVELOPE_MIN_2X = 232
_ENVELOPE_MAX_2X = 2180


def _turn_with_score_delta(
    *,
    shipchange: int = 0,
    freighterchange: int = 0,
):
    turn = single_ship_turn(
        turn_number=_HOST_TURN,
        ship_id=1,
        owner_id=_OWNER_ID,
        x=100,
        y=100,
    )
    turn = replace(turn, ships=[])
    score = replace(
        turn.scores[0],
        turn=_HOST_TURN,
        ownerid=_OWNER_ID,
        shipchange=shipchange,
        freighterchange=freighterchange,
    )
    return replace(turn, scores=[score])


def _known_warship(*, record_id: str) -> FleetShipRecord:
    return FleetShipRecord(
        record_id=record_id,
        fields=FleetShipRecordFields(hull=FleetFieldKnown(24)),
        build_option_sets=[
            FleetBuildOptionSet(hull_id=24, engine_id=1, beam_id=1, beam_count=2, launcher_count=0)
        ],
    )


def _persist_row(
    persistence: InferenceRowPersistenceService,
    *,
    status: str,
    placeholders: list[dict[str, object]] | None = None,
    departure_pins: list[dict[str, object]] | None = None,
) -> None:
    persistence.put_row(
        _GAME_ID,
        _PERSPECTIVE,
        _HOST_TURN,
        _OWNER_ID,
        PersistedInferenceRow(
            status=status,
            summary=status,
            solution_count=0,
            is_complete=True,
            solutions=[],
            placeholders=placeholders,
            leftover=(
                {"kind": "unknown_loss_bound", "lowerBound2x": 0}
                if status == STATUS_UNCHARACTERIZED_ROSTER
                else None
            ),
            departure_pins=departure_pins,
        ),
    )


def _apply_fleet(
    turn,
    *,
    prior_records: list[FleetShipRecord],
    persistence: InferenceRowPersistenceService,
):
    snapshot = ensure_fleet_baseline(_GAME_ID, _PERSPECTIVE, turn)
    ledger_for_player(snapshot, _OWNER_ID).records.extend(prior_records)
    return apply_fleet_turn_delta(
        snapshot,
        turn,
        inference_materialization=FleetInferenceMaterialization(
            inference=FleetInferenceSupport(
                scores_services=ScoresExportContext(persistence=persistence),
            ),
            load_turn=lambda _turn_number: turn,
        ),
    )


def test_exact_set_two_named_records_leave_the_active_ledger():
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    pins = (
        ExactSetDeparturePin(
            ship_class="warship",
            records=(
                ExactSetPinRecord(record_id="r1", disposition="lost"),
                ExactSetPinRecord(record_id="r2", disposition="lost"),
            ),
        ),
    )
    _persist_row(
        persistence,
        status=STATUS_EXACT,
        departure_pins=departure_pins_to_json(pins),
    )
    snapshot = _apply_fleet(
        _turn_with_score_delta(shipchange=-2),
        prior_records=[_known_warship(record_id="r1"), _known_warship(record_id="r2")],
        persistence=persistence,
    )
    ledger = ledger_for_player(snapshot, _OWNER_ID)
    by_id = {record.record_id: record for record in ledger.records}
    assert by_id["r1"].disposition == "lost"
    assert by_id["r2"].disposition == "lost"
    assert all(record.disposition != "active" for record in ledger.records)
    for record in ledger.records:
        change_events = [event for event in record.events if event.kind == "disposition_change"]
        assert len(change_events) == 1
        assert change_events[0].source == "scores.inference"
        assert change_events[0].payload["disposition"] == "lost"


def test_gift_exact_set_retires_named_record_as_traded_with_counterparty():
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    pins = (
        ExactSetDeparturePin(
            ship_class="warship",
            records=(
                ExactSetPinRecord(
                    record_id="gifted",
                    disposition="traded",
                    counterparty_player_id=5,
                ),
            ),
        ),
    )
    _persist_row(
        persistence,
        status=STATUS_EXACT,
        departure_pins=departure_pins_to_json(pins),
    )
    snapshot = _apply_fleet(
        _turn_with_score_delta(shipchange=-1),
        prior_records=[
            _known_warship(record_id="gifted"),
            _known_warship(record_id="stayer"),
        ],
        persistence=persistence,
    )
    ledger = ledger_for_player(snapshot, _OWNER_ID)
    by_id = {record.record_id: record for record in ledger.records}
    assert by_id["gifted"].disposition == "traded"
    assert by_id["stayer"].disposition == "active"
    traded_events = [
        event for event in by_id["gifted"].events if event.kind == "disposition_change"
    ]
    assert len(traded_events) == 1
    assert traded_events[0].payload["disposition"] == "traded"
    assert traded_events[0].payload["counterpartyPlayerId"] == 5
    assert not any(event.kind == "disposition_change" for event in by_id["stayer"].events)


def test_spec_only_pin_does_not_flip_disposition():
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    _persist_row(persistence, status=STATUS_EXACT)
    prior = [_known_warship(record_id=f"same-{index}") for index in range(10)]
    snapshot = _apply_fleet(
        _turn_with_score_delta(shipchange=-1),
        prior_records=prior,
        persistence=persistence,
    )
    ledger = ledger_for_player(snapshot, _OWNER_ID)
    assert len(ledger.records) == 10
    assert all(record.disposition == "active" for record in ledger.records)
    assert all(
        event.kind != "disposition_change" for record in ledger.records for event in record.events
    )


def test_placeholder_departure_persist_does_not_create_fleet_rows():
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    departure = placeholder_departure_to_json(PlaceholderDeparture(ship_class="warship", count=2))
    _persist_row(
        persistence,
        status=STATUS_UNCHARACTERIZED_ROSTER,
        placeholders=[departure],
    )
    snapshot = _apply_fleet(
        _turn_with_score_delta(shipchange=-2),
        prior_records=[],
        persistence=persistence,
    )
    ledger = ledger_for_player(snapshot, _OWNER_ID)
    assert ledger.records == []


def test_placeholder_departure_does_not_explode_onto_plus_count_rows():
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    _persist_row(
        persistence,
        status=STATUS_MODERATE_RESIDUAL,
        placeholders=[
            {
                "id": UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID,
                "hullId": UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID,
                "count": 2,
                "militaryScoreDelta2xMin": _ENVELOPE_MIN_2X,
                "militaryScoreDelta2xMax": _ENVELOPE_MAX_2X,
                "buildSlotUsage": 1,
            },
            {
                "id": PLACEHOLDER_DEPARTURE_ID,
                "shipClass": "warship",
                "count": 2,
            },
        ],
    )
    snapshot = _apply_fleet(
        _turn_with_score_delta(shipchange=2),
        prior_records=[],
        persistence=persistence,
    )
    ledger = ledger_for_player(snapshot, _OWNER_ID)
    assert len(ledger.records) == 2
    assert all(record.disposition == "active" for record in ledger.records)
    for record in ledger.records:
        assert len(record.build_option_sets) == 1
        option_set = record.build_option_sets[0]
        assert option_set.combo_id == UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID
        assert option_set.hull_id == UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID
        assert option_set.military_score_delta_2x_min == _ENVELOPE_MIN_2X
        assert option_set.military_score_delta_2x_max == _ENVELOPE_MAX_2X

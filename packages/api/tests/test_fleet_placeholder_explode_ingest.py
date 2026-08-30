"""Fleet ingest explodes persist placeholders onto unit inferred acquisition rows."""

from __future__ import annotations

from dataclasses import replace

from api.analytics.fleet.chain import apply_fleet_turn_delta, ensure_fleet_baseline
from api.analytics.fleet.held_solutions import FleetInferenceMaterialization, FleetInferenceSupport
from api.analytics.fleet.types import FleetFieldUnknown
from api.analytics.military_score_inference.post_unsat_placeholders import (
    UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID,
)
from api.analytics.military_score_inference.ship_build_combos import GENERIC_FREIGHTER_COMBO_ID
from api.analytics.military_score_inference.solver import STATUS_MODERATE_RESIDUAL
from api.analytics.scores.export_services import ScoresExportContext
from api.concepts.hulls import (
    GENERIC_FREIGHTER_SENTINEL_HULL_ID,
    UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID,
)
from api.serialization.inference_row_persistence import PersistedInferenceRow
from api.services.inference_row_persistence_service import InferenceRowPersistenceService
from api.storage.memory_asset import MemoryAssetBackend

from tests.fleet_fixtures import ledger_for_player, single_ship_turn

_ENVELOPE_MIN_2X = 232
_ENVELOPE_MAX_2X = 2180


def _turn_with_score_delta(
    *,
    turn_number: int,
    owner_id: int,
    shipchange: int = 0,
    freighterchange: int = 0,
):
    turn = single_ship_turn(turn_number=turn_number, ship_id=1, owner_id=owner_id, x=100, y=100)
    turn = replace(turn, ships=[])
    score = replace(
        turn.scores[0],
        turn=turn_number,
        ownerid=owner_id,
        shipchange=shipchange,
        freighterchange=freighterchange,
    )
    return replace(turn, scores=[score])


def _inference_materialization(
    inference: FleetInferenceSupport,
    turn,
) -> FleetInferenceMaterialization:
    return FleetInferenceMaterialization(
        inference=inference,
        load_turn=lambda _turn_number: turn,
    )


def _unknown_military_placeholder(*, count: int) -> dict[str, object]:
    return {
        "id": UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID,
        "hullId": UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID,
        "count": count,
        "militaryScoreDelta2xMin": _ENVELOPE_MIN_2X,
        "militaryScoreDelta2xMax": _ENVELOPE_MAX_2X,
        "buildSlotUsage": 1,
    }


def _generic_freighter_placeholder(*, count: int) -> dict[str, object]:
    return {
        "id": GENERIC_FREIGHTER_COMBO_ID,
        "hullId": GENERIC_FREIGHTER_SENTINEL_HULL_ID,
        "count": count,
        "buildSlotUsage": 1,
    }


def _ingest_with_persist_placeholders(
    *,
    shipchange: int,
    freighterchange: int,
    placeholders: list[dict[str, object]],
):
    turn = _turn_with_score_delta(
        turn_number=111,
        owner_id=8,
        shipchange=shipchange,
        freighterchange=freighterchange,
    )
    persistence = InferenceRowPersistenceService(MemoryAssetBackend(initial={}))
    persistence.put_row(
        628580,
        1,
        111,
        8,
        PersistedInferenceRow(
            status=STATUS_MODERATE_RESIDUAL,
            summary="Moderate military leftover (11)",
            solution_count=0,
            is_complete=True,
            solutions=[],
            placeholders=placeholders,
            unexplained_military_delta_2x=22,
        ),
    )
    snapshot = apply_fleet_turn_delta(
        ensure_fleet_baseline(628580, 1, turn),
        turn,
        inference_materialization=_inference_materialization(
            FleetInferenceSupport(scores_services=ScoresExportContext(persistence=persistence)),
            turn,
        ),
    )
    return ledger_for_player(snapshot, 8)


def test_unknown_military_persist_explodes_to_unit_rows_with_hull_sentinel_and_envelope():
    """Fails if persist placeholders are ignored: scoreboard shipchange alone has no envelope."""
    ledger = _ingest_with_persist_placeholders(
        shipchange=3,
        freighterchange=0,
        placeholders=[_unknown_military_placeholder(count=3)],
    )
    assert len(ledger.records) == 3
    for record in ledger.records:
        assert record.fields.hull == FleetFieldUnknown()
        assert len(record.build_option_sets) == 1
        option_set = record.build_option_sets[0]
        assert option_set.hull_id == UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID
        assert option_set.combo_id == UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID
        assert option_set.military_score_delta_2x_min == _ENVELOPE_MIN_2X
        assert option_set.military_score_delta_2x_max == _ENVELOPE_MAX_2X
        assert option_set.engine_id is None
        assert option_set.beam_id is None
        assert option_set.torp_id is None


def test_generic_freighter_persist_explodes_to_unit_rows_with_hull_sentinel():
    ledger = _ingest_with_persist_placeholders(
        shipchange=0,
        freighterchange=2,
        placeholders=[_generic_freighter_placeholder(count=2)],
    )
    assert len(ledger.records) == 2
    for record in ledger.records:
        assert len(record.build_option_sets) == 1
        option_set = record.build_option_sets[0]
        assert option_set.hull_id == GENERIC_FREIGHTER_SENTINEL_HULL_ID
        assert option_set.combo_id == GENERIC_FREIGHTER_COMBO_ID
        assert option_set.military_score_delta_2x_min is None
        assert option_set.military_score_delta_2x_max is None


def test_same_row_military_and_freighter_placeholders_explode_by_class():
    ledger = _ingest_with_persist_placeholders(
        shipchange=2,
        freighterchange=1,
        placeholders=[
            _unknown_military_placeholder(count=2),
            _generic_freighter_placeholder(count=1),
        ],
    )
    warships = [
        record
        for record in ledger.records
        if record.build_option_sets
        and record.build_option_sets[0].hull_id == UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID
    ]
    freighters = [
        record
        for record in ledger.records
        if record.build_option_sets
        and record.build_option_sets[0].hull_id == GENERIC_FREIGHTER_SENTINEL_HULL_ID
    ]
    assert len(ledger.records) == 3
    assert len(warships) == 2
    assert len(freighters) == 1
    assert all(
        option_set.military_score_delta_2x_min == _ENVELOPE_MIN_2X
        and option_set.military_score_delta_2x_max == _ENVELOPE_MAX_2X
        for record in warships
        for option_set in record.build_option_sets
    )
    assert all(
        option_set.military_score_delta_2x_min is None
        for record in freighters
        for option_set in record.build_option_sets
    )

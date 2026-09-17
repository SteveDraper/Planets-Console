"""Tests for typed HostTurnFunctionalTarget codecs."""

from __future__ import annotations

from api.analytics.military_score_inference.accelerated_start import (
    AcceleratedInferenceSegment,
)
from api.analytics.military_score_inference.analytic import infer_military_score_build
from api.analytics.military_score_inference.host_turn_targets import (
    HostTurnFunctionalTarget,
    functional_host_turn_target_from_segment_payload,
    host_turn_functional_target_from_persistence_dict,
    host_turn_functional_target_from_wire_dict,
    host_turn_functional_target_to_persistence_dict,
    host_turn_functional_target_to_wire_dict,
    host_turn_targets_from_wire_event,
)
from api.analytics.military_score_inference.inference_accelerated import (
    accelerated_split_status,
    build_accelerated_segment_payload,
)
from api.analytics.military_score_inference.inference_api_payload import (
    product_payload_fields,
)
from api.analytics.military_score_inference.models import InferenceResult
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_MODERATE_RESIDUAL,
    STATUS_NO_EXACT_SOLUTION,
    STATUS_TIME_LIMITED,
)
from api.analytics.military_score_inference.uncharacterized_roster import (
    STATUS_UNCHARACTERIZED_ROSTER,
)
from api.analytics.military_score_inference.uncharacterized_roster_types import (
    LatticeSignature,
    PlaceholderBuild,
    PlaceholderDeparture,
    UnknownLossBoundLeftover,
)
from api.analytics.scores.host_turn_export import (
    _payload_from_functional_target,
    functional_target_for_host_turn,
    host_turn_targets_from_persisted_row,
)
from api.concepts.hulls import UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID
from api.serialization.inference_row_persistence import (
    INFERENCE_ROW_PERSISTENCE_VERSION,
    PersistedInferenceRow,
    persisted_inference_row_from_json,
    persisted_inference_row_to_json,
)
from api.serialization.uncharacterized_roster import PLACEHOLDER_DEPARTURE_ID
from api.transport.inference_stream_wire import inference_api_payload_to_wire_complete

from tests.fixtures.military_score_inference import _observation
from tests.inference_corpus.fixtures import load_turn_fixture


def _sample_wire_target() -> dict[str, object]:
    turn = load_turn_fixture("628580/1/turns/3.json")
    score = next(entry for entry in turn.scores if entry.ownerid == 11)
    wire_complete = inference_api_payload_to_wire_complete(infer_military_score_build(score, turn))
    targets = host_turn_targets_from_wire_event(wire_complete)
    assert targets
    return host_turn_functional_target_to_wire_dict(targets[0])


def test_host_turn_functional_target_wire_round_trip():
    wire = _sample_wire_target()
    target = host_turn_functional_target_from_wire_dict(wire)
    assert isinstance(target, HostTurnFunctionalTarget)
    assert host_turn_functional_target_to_wire_dict(target) == wire


def test_host_turn_functional_target_persistence_round_trip():
    target = host_turn_functional_target_from_wire_dict(_sample_wire_target())
    persisted = host_turn_functional_target_to_persistence_dict(target)
    restored = host_turn_functional_target_from_persistence_dict(persisted)
    assert restored == target


def test_persisted_inference_row_host_turn_targets_round_trip():
    target = host_turn_functional_target_from_wire_dict(_sample_wire_target())
    row = PersistedInferenceRow(
        status="exact",
        summary="ok",
        solution_count=target.solution_count,
        is_complete=True,
        solutions=target.solutions,
        host_turn_targets=[target],
        persistence_version=INFERENCE_ROW_PERSISTENCE_VERSION,
    )
    restored = persisted_inference_row_from_json(persisted_inference_row_to_json(row))
    assert restored == row
    stored_targets = persisted_inference_row_to_json(row)["host_turn_targets"]
    assert stored_targets
    assert "host_turn" in stored_targets[0]
    assert "hostTurn" not in stored_targets[0]


def test_legacy_camel_case_persistence_dict_still_loads():
    wire = _sample_wire_target()
    row = persisted_inference_row_from_json(
        {
            "status": "exact",
            "summary": "ok",
            "solution_count": 1,
            "is_complete": True,
            "solutions": [],
            "host_turn_targets": [wire],
            "persistence_version": INFERENCE_ROW_PERSISTENCE_VERSION,
        },
    )
    assert row.host_turn_targets
    assert row.host_turn_targets[0].host_turn == wire["hostTurn"]


def test_functional_target_for_host_turn_uses_typed_fields():
    target = host_turn_functional_target_from_wire_dict(_sample_wire_target())
    row = PersistedInferenceRow(
        status="exact",
        summary="ok",
        solution_count=target.solution_count,
        is_complete=True,
        solutions=[],
        host_turn_targets=[target],
        persistence_version=INFERENCE_ROW_PERSISTENCE_VERSION,
    )
    targets = host_turn_targets_from_persisted_row(row)
    resolved = functional_target_for_host_turn(targets, target.host_turn)
    assert resolved is target


def test_functional_target_time_limited_maps_to_stopped_search_status():
    target = host_turn_functional_target_from_wire_dict(_sample_wire_target())
    time_limited = HostTurnFunctionalTarget(
        host_turn=target.host_turn,
        status=STATUS_TIME_LIMITED,
        solution_count=target.solution_count,
        military_delta_2x=target.military_delta_2x,
        warship_delta=target.warship_delta,
        freighter_delta=target.freighter_delta,
        solutions=target.solutions,
    )
    payload = _payload_from_functional_target(time_limited)
    assert payload.search_status == "stopped"


def test_functional_target_residual_maps_to_complete_with_leftover():
    target = host_turn_functional_target_from_wire_dict(_sample_wire_target())
    product = product_payload_fields(
        STATUS_MODERATE_RESIDUAL,
        leftover=22,
    )
    residual = HostTurnFunctionalTarget(
        host_turn=target.host_turn,
        status=STATUS_MODERATE_RESIDUAL,
        solution_count=0,
        military_delta_2x=22,
        warship_delta=target.warship_delta,
        freighter_delta=target.freighter_delta,
        solutions=[],
        product=product,
    )
    payload = _payload_from_functional_target(residual)
    assert payload.search_status == "complete"
    assert payload.product.status == STATUS_MODERATE_RESIDUAL
    assert payload.product.placeholders == []
    assert payload.product.unexplained_military_delta_2x == 22


def test_payload_from_functional_target_reads_leftover_slot_not_observation_delta():
    product = product_payload_fields(
        STATUS_MODERATE_RESIDUAL,
        leftover=22,
    )
    residual = HostTurnFunctionalTarget(
        host_turn=2,
        status=STATUS_MODERATE_RESIDUAL,
        solution_count=0,
        military_delta_2x=999,
        warship_delta=0,
        freighter_delta=0,
        solutions=[],
        product=product,
    )
    payload = _payload_from_functional_target(residual)
    assert payload.product.unexplained_military_delta_2x == 22
    assert payload.product.placeholders == []


def test_functional_host_turn_target_strips_segment_diagnostics():
    segment = {
        "segmentId": "seg-1",
        "hostTurn": 2,
        "status": "exact",
        "solutionCount": 1,
        "militaryDelta2x": 10,
        "warshipDelta": 1,
        "freighterDelta": 0,
        "policyStepsAttempted": ["baseline"],
        "solutions": [{"objectiveValue": 1.0, "actions": [], "shipBuilds": []}],
    }
    target = functional_host_turn_target_from_segment_payload(segment)
    wire = host_turn_functional_target_to_wire_dict(target)
    assert "segmentId" not in wire
    assert "policyStepsAttempted" not in wire
    assert "placeholders" not in wire
    assert "unexplainedMilitaryDelta2x" not in wire
    assert target.product.placeholders is None
    assert target.product.unexplained_military_delta_2x is None


def _legacy_target_dict(*, status: str, military_delta_2x: int) -> dict[str, object]:
    return {
        "hostTurn": 2,
        "status": status,
        "solutionCount": 0,
        "militaryDelta2x": military_delta_2x,
        "warshipDelta": 0,
        "freighterDelta": 0,
        "solutions": [],
    }


def test_legacy_target_dict_without_product_slots_still_decodes():
    exact = host_turn_functional_target_from_wire_dict(
        _legacy_target_dict(status=STATUS_EXACT, military_delta_2x=10),
    )
    assert exact.product.placeholders is None
    assert exact.product.unexplained_military_delta_2x is None
    persisted_exact = host_turn_functional_target_from_persistence_dict(
        {
            "host_turn": 2,
            "status": STATUS_EXACT,
            "solution_count": 0,
            "military_delta_2x": 10,
            "warship_delta": 0,
            "freighter_delta": 0,
            "solutions": [],
        },
    )
    assert persisted_exact.product.placeholders is None
    assert persisted_exact.product.unexplained_military_delta_2x is None

    residual = host_turn_functional_target_from_wire_dict(
        _legacy_target_dict(status=STATUS_MODERATE_RESIDUAL, military_delta_2x=22),
    )
    assert residual.product.placeholders == []
    assert residual.product.unexplained_military_delta_2x == 22
    assert residual.military_delta_2x == 22
    persisted_residual = host_turn_functional_target_from_persistence_dict(
        {
            "host_turn": 2,
            "status": STATUS_MODERATE_RESIDUAL,
            "solution_count": 0,
            "military_delta_2x": 22,
            "warship_delta": 0,
            "freighter_delta": 0,
            "solutions": [],
        },
    )
    assert persisted_residual.product.placeholders == []
    assert persisted_residual.product.unexplained_military_delta_2x == 22


def test_host_turn_functional_target_product_slots_round_trip():
    product = product_payload_fields(
        STATUS_MODERATE_RESIDUAL,
        leftover=22,
    )
    target = HostTurnFunctionalTarget(
        host_turn=2,
        status=STATUS_MODERATE_RESIDUAL,
        solution_count=0,
        military_delta_2x=40,
        warship_delta=0,
        freighter_delta=0,
        solutions=[],
        product=product,
    )
    wire = host_turn_functional_target_to_wire_dict(target)
    assert wire["placeholders"] == []
    assert wire["unexplainedMilitaryDelta2x"] == 22
    assert wire["militaryDelta2x"] == 40
    restored_wire = host_turn_functional_target_from_wire_dict(wire)
    assert restored_wire == target
    assert host_turn_functional_target_to_wire_dict(restored_wire) == wire

    persisted = host_turn_functional_target_to_persistence_dict(target)
    assert persisted["placeholders"] == []
    assert persisted["unexplained_military_delta_2x"] == 22
    assert "unexplainedMilitaryDelta2x" not in persisted
    restored_persisted = host_turn_functional_target_from_persistence_dict(persisted)
    assert restored_persisted == target


def test_segment_payload_populates_leftover_from_observation_delta():
    segment = {
        "segmentId": "seg-residual",
        "hostTurn": 1,
        "status": STATUS_MODERATE_RESIDUAL,
        "solutionCount": 0,
        "militaryDelta2x": 22,
        "warshipDelta": 0,
        "freighterDelta": 0,
        "policyStepsAttempted": ["baseline"],
        "solutions": [],
    }
    target = functional_host_turn_target_from_segment_payload(segment)
    assert target.military_delta_2x == 22
    assert target.product.placeholders == []
    assert target.product.unexplained_military_delta_2x == 22
    wire = host_turn_functional_target_to_wire_dict(target)
    assert wire["unexplainedMilitaryDelta2x"] == 22
    assert wire["placeholders"] == []


def test_persisted_inference_row_round_trips_target_product_slots():
    product = product_payload_fields(
        STATUS_MODERATE_RESIDUAL,
        leftover=22,
    )
    target = HostTurnFunctionalTarget(
        host_turn=2,
        status=STATUS_MODERATE_RESIDUAL,
        solution_count=0,
        military_delta_2x=22,
        warship_delta=0,
        freighter_delta=0,
        solutions=[],
        product=product,
    )
    row = PersistedInferenceRow(
        status=STATUS_MODERATE_RESIDUAL,
        summary="Moderate military leftover (11)",
        solution_count=0,
        is_complete=True,
        solutions=[],
        host_turn_targets=[target],
        persistence_version=INFERENCE_ROW_PERSISTENCE_VERSION,
    )
    restored = persisted_inference_row_from_json(persisted_inference_row_to_json(row))
    assert restored.host_turn_targets == [target]
    stored_target = persisted_inference_row_to_json(row)["host_turn_targets"][0]
    assert stored_target["placeholders"] == []
    assert stored_target["unexplained_military_delta_2x"] == 22


_ROSTER_LEFTOVER = {"kind": "unknown_loss_bound", "lowerBound2x": 800}
_ROSTER_SIGNATURES = [
    {
        "shipClass": "warship",
        "build": {"id": "unknown_military_ship", "count": 1},
        "departure": {
            "id": PLACEHOLDER_DEPARTURE_ID,
            "shipClass": "warship",
            "count": 1,
        },
    }
]


def _roster_product():
    return product_payload_fields(
        STATUS_UNCHARACTERIZED_ROSTER,
        placeholders=[],
        leftover=22,
        tagged_leftover=_ROSTER_LEFTOVER,
        lattice_signatures=_ROSTER_SIGNATURES,
    )


def test_host_turn_functional_target_roster_product_round_trip():
    product = _roster_product()
    target = HostTurnFunctionalTarget(
        host_turn=2,
        status=STATUS_UNCHARACTERIZED_ROSTER,
        solution_count=0,
        military_delta_2x=40,
        warship_delta=-1,
        freighter_delta=0,
        solutions=[],
        product=product,
    )
    wire = host_turn_functional_target_to_wire_dict(target)
    assert "unexplainedMilitaryDelta2x" not in wire
    assert wire["leftover"] == _ROSTER_LEFTOVER
    assert wire["latticeSignatures"] == _ROSTER_SIGNATURES
    assert wire["placeholders"] == []
    restored_wire = host_turn_functional_target_from_wire_dict(wire)
    assert restored_wire.product.leftover == _ROSTER_LEFTOVER
    assert restored_wire.product.lattice_signatures == _ROSTER_SIGNATURES
    assert restored_wire.product.unexplained_military_delta_2x is None
    assert host_turn_functional_target_to_wire_dict(restored_wire) == wire

    persisted = host_turn_functional_target_to_persistence_dict(target)
    assert "unexplained_military_delta_2x" not in persisted
    assert persisted["leftover"] == _ROSTER_LEFTOVER
    assert persisted["lattice_signatures"] == _ROSTER_SIGNATURES
    restored_persisted = host_turn_functional_target_from_persistence_dict(persisted)
    assert restored_persisted.product == product


def test_payload_from_functional_target_exposes_roster_leftover_and_signatures():
    target = HostTurnFunctionalTarget(
        host_turn=2,
        status=STATUS_UNCHARACTERIZED_ROSTER,
        solution_count=0,
        military_delta_2x=40,
        warship_delta=-1,
        freighter_delta=0,
        solutions=[],
        product=_roster_product(),
    )
    payload = _payload_from_functional_target(target)
    assert payload.search_status == "complete"
    assert payload.product.status == STATUS_UNCHARACTERIZED_ROSTER
    assert payload.product.unexplained_military_delta_2x is None
    assert payload.product.leftover == _ROSTER_LEFTOVER
    assert payload.product.lattice_signatures == _ROSTER_SIGNATURES
    assert payload.product.placeholders == []


def test_segment_payload_preserves_roster_leftover_and_signatures():
    segment = {
        "segmentId": "seg-roster",
        "hostTurn": 1,
        "status": STATUS_UNCHARACTERIZED_ROSTER,
        "solutionCount": 0,
        "militaryDelta2x": 40,
        "warshipDelta": -1,
        "freighterDelta": 0,
        "policyStepsAttempted": ["baseline"],
        "solutions": [],
        "placeholders": [],
        "leftover": _ROSTER_LEFTOVER,
        "latticeSignatures": _ROSTER_SIGNATURES,
        "unexplainedMilitaryDelta2x": 22,
    }
    target = functional_host_turn_target_from_segment_payload(segment)
    assert target.product.status == STATUS_UNCHARACTERIZED_ROSTER
    assert target.product.unexplained_military_delta_2x is None
    assert target.product.leftover == _ROSTER_LEFTOVER
    assert target.product.lattice_signatures == _ROSTER_SIGNATURES
    wire = host_turn_functional_target_to_wire_dict(target)
    assert "unexplainedMilitaryDelta2x" not in wire
    assert wire["leftover"] == _ROSTER_LEFTOVER
    assert wire["latticeSignatures"] == _ROSTER_SIGNATURES


def test_accelerated_split_status_roster_segment_is_not_exact():
    assert (
        accelerated_split_status(
            [{"status": STATUS_EXACT}, {"status": STATUS_UNCHARACTERIZED_ROSTER}],
            False,
        )
        == STATUS_UNCHARACTERIZED_ROSTER
    )


def test_accelerated_split_status_no_exact_still_wins_over_roster():
    assert (
        accelerated_split_status(
            [
                {"status": STATUS_NO_EXACT_SOLUTION},
                {"status": STATUS_UNCHARACTERIZED_ROSTER},
            ],
            False,
        )
        == STATUS_NO_EXACT_SOLUTION
    )


def test_build_accelerated_segment_payload_includes_roster_product_fields():
    segment = AcceleratedInferenceSegment(
        segment_id="reported-host-turn",
        host_turn=2,
        military_delta_2x=40,
        warship_delta=-1,
        freighter_delta=0,
        priority_point_delta=0,
    )
    result = InferenceResult(
        status=STATUS_UNCHARACTERIZED_ROSTER,
        solutions=(),
        diagnostics={},
        leftover=UnknownLossBoundLeftover(lower_bound_2x=800),
        placeholder_departures=(PlaceholderDeparture(ship_class="warship", count=1),),
        lattice_signatures=(
            LatticeSignature(
                ship_class="warship",
                build=PlaceholderBuild(
                    id="unknown_military_ship",
                    hull_id=UNKNOWN_MILITARY_SHIP_SENTINEL_HULL_ID,
                    count=1,
                    build_slot_usage=1,
                    military_score_delta_2x_min=0,
                    military_score_delta_2x_max=40,
                ),
                departure=PlaceholderDeparture(ship_class="warship", count=1),
            ),
        ),
    )
    payload = build_accelerated_segment_payload(
        segment,
        _observation(military_delta_2x=40, warship_delta=-1),
        result,
        None,
        policy_steps_attempted=["baseline"],
        step_diagnostics=[],
    )
    assert payload["status"] == STATUS_UNCHARACTERIZED_ROSTER
    assert "unexplainedMilitaryDelta2x" not in payload
    assert payload["leftover"] == _ROSTER_LEFTOVER
    assert payload["placeholders"]
    assert payload["placeholders"][0]["id"] == PLACEHOLDER_DEPARTURE_ID
    assert payload["latticeSignatures"]
    target = functional_host_turn_target_from_segment_payload(payload)
    assert target.product.leftover == _ROSTER_LEFTOVER
    assert target.product.lattice_signatures == payload["latticeSignatures"]
    assert target.product.unexplained_military_delta_2x is None

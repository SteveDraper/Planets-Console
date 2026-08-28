"""Tests for typed HostTurnFunctionalTarget codecs."""

from __future__ import annotations

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
from api.analytics.military_score_inference.inference_api_payload import (
    product_payload_fields,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_MODERATE_RESIDUAL,
    STATUS_TIME_LIMITED,
)
from api.analytics.scores.host_turn_export import (
    _payload_from_functional_target,
    functional_target_for_host_turn,
    host_turn_targets_from_persisted_row,
)
from api.serialization.inference_row_persistence import (
    INFERENCE_ROW_PERSISTENCE_VERSION,
    PersistedInferenceRow,
    persisted_inference_row_from_json,
    persisted_inference_row_to_json,
)
from api.transport.inference_stream_wire import inference_api_payload_to_wire_complete

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
    placeholders, leftover = product_payload_fields(
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
        placeholders=placeholders,
        unexplained_military_delta_2x=leftover,
    )
    payload = _payload_from_functional_target(residual)
    assert payload.search_status == "complete"
    assert payload.status == STATUS_MODERATE_RESIDUAL
    assert payload.placeholders == []
    assert payload.unexplained_military_delta_2x == 22


def test_payload_from_functional_target_reads_leftover_slot_not_observation_delta():
    placeholders, leftover = product_payload_fields(
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
        placeholders=placeholders,
        unexplained_military_delta_2x=leftover,
    )
    payload = _payload_from_functional_target(residual)
    assert payload.unexplained_military_delta_2x == 22
    assert payload.placeholders == []


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
    assert target.placeholders is None
    assert target.unexplained_military_delta_2x is None


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
    assert exact.placeholders is None
    assert exact.unexplained_military_delta_2x is None
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
    assert persisted_exact.placeholders is None
    assert persisted_exact.unexplained_military_delta_2x is None

    residual = host_turn_functional_target_from_wire_dict(
        _legacy_target_dict(status=STATUS_MODERATE_RESIDUAL, military_delta_2x=22),
    )
    assert residual.placeholders == []
    assert residual.unexplained_military_delta_2x == 22
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
    assert persisted_residual.placeholders == []
    assert persisted_residual.unexplained_military_delta_2x == 22


def test_host_turn_functional_target_product_slots_round_trip():
    placeholders, leftover = product_payload_fields(
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
        placeholders=placeholders,
        unexplained_military_delta_2x=leftover,
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
    assert target.placeholders == []
    assert target.unexplained_military_delta_2x == 22
    wire = host_turn_functional_target_to_wire_dict(target)
    assert wire["unexplainedMilitaryDelta2x"] == 22
    assert wire["placeholders"] == []


def test_persisted_inference_row_round_trips_target_product_slots():
    placeholders, leftover = product_payload_fields(
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
        placeholders=placeholders,
        unexplained_military_delta_2x=leftover,
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

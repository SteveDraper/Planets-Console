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
from api.analytics.scores.host_turn_export import (
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

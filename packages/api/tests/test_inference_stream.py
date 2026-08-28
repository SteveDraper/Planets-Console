"""Tests for scores inference NDJSON streaming."""

import json

import pytest
from api.analytics.military_score_inference.inference_admission import (
    admission_skip_complete_event,
    admission_skip_for_status,
)
from api.analytics.military_score_inference.inference_api_payload import (
    STATUS_VIEWPOINT_OWNER,
    inference_api_payload,
)
from api.analytics.military_score_inference.models import (
    InferenceResult,
    InferenceSolution,
    InferenceSolutionAction,
)
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_MINE_SCORE_RESIDUAL,
    STATUS_MODERATE_RESIDUAL,
    STATUS_NO_EXACT_SOLUTION,
)
from api.transport.inference_stream import (
    inference_complete_event,
    inference_solution_event,
    stream_inference_ndjson,
)
from api.transport.inference_stream_wire import (
    domain_event_to_wire_events,
    inference_api_payload_to_wire_complete,
    row_complete_to_complete_wire_event,
)

from tests.fixtures.military_score_inference import _observation


def test_stream_inference_ndjson_yields_ndjson_lines() -> None:
    items = [
        inference_solution_event([{"objectiveValue": 5, "actions": []}]),
        inference_complete_event(
            status="exact",
            summary="Best: built one ship",
            solution_count=1,
            is_complete=True,
            solutions=[{"objectiveValue": 5, "actions": []}],
        ),
    ]

    lines = list(stream_inference_ndjson(lambda: iter(items)))

    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["type"] == "solution"
    last = json.loads(lines[-1])
    assert last["type"] == "complete"
    assert last["status"] == "exact"
    assert last["solutionCount"] == 1
    assert last["solutions"] == [{"objectiveValue": 5, "actions": []}]


def test_skip_complete_carries_empty_placeholders_and_no_leftover() -> None:
    wire = admission_skip_complete_event(admission_skip_for_status(STATUS_VIEWPOINT_OWNER))
    assert wire["type"] == "complete"
    assert wire["status"] == STATUS_VIEWPOINT_OWNER
    assert wire["solutionCount"] == 0
    assert wire["solutions"] == []
    assert wire["placeholders"] == []
    assert "unexplainedMilitaryDelta2x" not in wire
    assert "diagnostics" not in wire


def test_residual_complete_carries_leftover_and_empty_placeholders() -> None:
    moderate = inference_complete_event(
        status=STATUS_MODERATE_RESIDUAL,
        summary="Moderate military leftover (11)",
        solution_count=0,
        is_complete=True,
        solutions=[],
        placeholders=[],
        unexplained_military_delta_2x=22,
    )
    mine = inference_complete_event(
        status=STATUS_MINE_SCORE_RESIDUAL,
        summary="Mine-score leftover (27)",
        solution_count=0,
        is_complete=True,
        solutions=[],
        placeholders=[],
        unexplained_military_delta_2x=54,
    )
    unsat = inference_complete_event(
        status=STATUS_NO_EXACT_SOLUTION,
        summary="No feasible build explanation found",
        solution_count=0,
        is_complete=True,
        solutions=[],
        placeholders=[],
        unexplained_military_delta_2x=40,
    )
    for wire in (moderate, mine, unsat):
        assert wire["type"] == "complete"
        assert wire["solutionCount"] == 0
        assert wire["solutions"] == []
        assert wire["placeholders"] == []
        assert isinstance(wire["unexplainedMilitaryDelta2x"], int)


def test_placeholder_complete_does_not_emit_solution_events() -> None:
    items = [
        inference_complete_event(
            status=STATUS_MODERATE_RESIDUAL,
            summary="Moderate military leftover (0)",
            solution_count=0,
            is_complete=True,
            solutions=[],
            placeholders=[],
            unexplained_military_delta_2x=0,
        )
    ]
    events = [json.loads(line) for line in stream_inference_ndjson(lambda: iter(items))]
    assert [event["type"] for event in events] == ["complete"]
    assert events[0]["solutionCount"] == 0
    assert events[0]["placeholders"] == []


@pytest.mark.parametrize(
    ("status", "military_delta_2x", "expected_summary"),
    [
        (STATUS_MODERATE_RESIDUAL, 22, "Moderate military leftover (11)"),
        (STATUS_MINE_SCORE_RESIDUAL, 54, "Mine-score leftover (27)"),
        (STATUS_NO_EXACT_SOLUTION, 40, "No feasible build explanation found"),
    ],
)
def test_residual_payload_carries_observation_leftover_and_empty_placeholders(
    status: str,
    military_delta_2x: int,
    expected_summary: str,
) -> None:
    payload = inference_api_payload(
        status=status,
        summary="caller summary must not leak leftover (0)",
        solutions=(),
        diagnostics={},
        observation=_observation(military_delta_2x=military_delta_2x),
    )
    wire = inference_api_payload_to_wire_complete(payload)
    events = [json.loads(line) for line in stream_inference_ndjson(lambda: iter([wire]))]

    assert payload["unexplainedMilitaryDelta2x"] == military_delta_2x
    assert payload["placeholders"] == []
    assert payload["solutionCount"] == 0
    assert payload["solutions"] == []
    assert payload["summary"] == expected_summary
    assert wire["type"] == "complete"
    assert wire["unexplainedMilitaryDelta2x"] == military_delta_2x
    assert wire["placeholders"] == []
    assert wire["solutionCount"] == 0
    assert wire["solutions"] == []
    assert wire["summary"] == expected_summary
    assert [event["type"] for event in events] == ["complete"]
    assert events[0]["solutionCount"] == 0
    assert events[0]["placeholders"] == []
    assert events[0]["unexplainedMilitaryDelta2x"] == military_delta_2x


@pytest.mark.parametrize(
    ("status", "expected_summary"),
    [
        (STATUS_MODERATE_RESIDUAL, "Moderate military leftover"),
        (STATUS_MINE_SCORE_RESIDUAL, "Mine-score leftover"),
        (STATUS_NO_EXACT_SOLUTION, "No feasible build explanation found"),
    ],
)
def test_residual_payload_omits_leftover_when_observation_missing(
    status: str,
    expected_summary: str,
) -> None:
    payload = inference_api_payload(
        status=status,
        summary="caller summary must not leak leftover (0)",
        solutions=(),
        diagnostics={},
    )
    wire = inference_api_payload_to_wire_complete(payload)

    assert "unexplainedMilitaryDelta2x" not in payload
    assert "unexplainedMilitaryDelta2x" not in wire
    assert payload["placeholders"] == []
    assert wire["placeholders"] == []
    assert payload["summary"] == expected_summary
    assert wire["summary"] == expected_summary
    assert "leftover (0)" not in payload["summary"]
    assert "leftover (0)" not in wire["summary"]
    assert payload["solutionCount"] == 0
    assert payload["solutions"] == []


def test_residual_payload_publishes_zero_leftover_from_observation() -> None:
    payload = inference_api_payload(
        status=STATUS_MODERATE_RESIDUAL,
        summary="caller summary must not leak leftover (0)",
        solutions=(),
        diagnostics={},
        observation=_observation(military_delta_2x=0),
    )
    wire = inference_api_payload_to_wire_complete(payload)

    assert payload["unexplainedMilitaryDelta2x"] == 0
    assert payload["summary"] == "Moderate military leftover (0)"
    assert wire["unexplainedMilitaryDelta2x"] == 0
    assert wire["summary"] == "Moderate military leftover (0)"
    assert wire["placeholders"] == []
    assert wire["solutionCount"] == 0


def test_row_complete_to_complete_wire_event_includes_solutions() -> None:
    solution = InferenceSolution(
        objective_value=42,
        actions=(InferenceSolutionAction(action_id="action_a", label="Build fighter", count=2),),
    )
    wire = row_complete_to_complete_wire_event(
        row_complete_with_summary(
            InferenceResult(status=STATUS_EXACT, solutions=(solution,), diagnostics={}),
            summary="Best: built fighters",
        ),
    )

    assert wire["type"] == "complete"
    assert wire["solutionCount"] == 1
    assert isinstance(wire.get("solutions"), list)
    assert len(wire["solutions"]) == 1
    assert wire["solutions"][0]["objectiveValue"] == 42
    assert wire["solutions"][0]["actions"][0]["actionId"] == "action_a"


def test_row_complete_to_complete_wire_event_promotes_fleet_torp_fields() -> None:
    promoted = inference_api_payload_to_wire_complete(
        {
            "status": "exact",
            "summary": "Best: one build",
            "solutionCount": 1,
            "isComplete": True,
            "solutions": [],
            "diagnostics": {
                "fleetTorpInputStatus": "applied",
                "fleetTorpOverlay": {"beliefSetTorpIds": [4, 8]},
            },
        }
    )

    assert promoted["fleetTorpInputStatus"] == "applied"
    assert promoted["fleetTorpOverlayBeliefSetTorpIds"] == [4, 8]
    assert promoted["diagnostics"]["fleetTorpInputStatus"] == "applied"


def test_inference_api_payload_to_wire_complete_rejects_invalid_fleet_torp_input_status() -> None:
    promoted = inference_api_payload_to_wire_complete(
        {
            "status": "exact",
            "summary": "Best: one build",
            "solutionCount": 1,
            "isComplete": True,
            "solutions": [],
            "fleetTorpInputStatus": "bogus",
            "diagnostics": {
                "fleetTorpInputStatus": "applied",
                "fleetTorpOverlay": {"beliefSetTorpIds": [4, 8]},
            },
        }
    )

    assert "fleetTorpInputStatus" not in promoted
    assert "fleetTorpOverlayBeliefSetTorpIds" not in promoted


def test_stream_inference_ndjson_yields_error_line_on_failure() -> None:
    def failing_loader():
        raise RuntimeError("simulated defect")

    lines = list(stream_inference_ndjson(failing_loader))

    assert len(lines) == 1
    error = json.loads(lines[0])
    assert error == {"type": "error", "detail": "Internal server error"}


def test_inference_solution_event_includes_fleet_torp_input_status() -> None:
    wire = inference_solution_event(
        [{"objectiveValue": 5, "actions": []}],
        fleet_torp_input_status="pending",
    )
    assert wire["fleetTorpInputStatus"] == "pending"


def test_inference_solution_event_omits_fleet_torp_input_status_when_none() -> None:
    wire = inference_solution_event([{"objectiveValue": 5, "actions": []}])
    assert "fleetTorpInputStatus" not in wire


def test_domain_event_held_solutions_updated_includes_fleet_torp_input_status(
    sample_turn,
) -> None:
    from api.analytics.military_score_inference.actions import ActionCatalog
    from api.analytics.military_score_inference.analytic import build_inference_observation
    from api.analytics.military_score_inference.inference_stream_domain_events import (
        HeldSolutionsUpdated,
    )

    score = sample_turn.scores[0]
    observation = build_inference_observation(score, sample_turn)
    solution = InferenceSolution(
        objective_value=10,
        actions=(InferenceSolutionAction(action_id="a1", label="Action A", count=1),),
    )
    event = HeldSolutionsUpdated(
        solutions=(solution,),
        catalog=ActionCatalog((), (), {}),
        observation=observation,
    )
    wire_events = domain_event_to_wire_events(
        event,
        observation=observation,
        turn=sample_turn,
        fleet_torp_input_status="applied",
    )
    assert len(wire_events) == 1
    assert wire_events[0]["type"] == "solution"
    assert wire_events[0]["fleetTorpInputStatus"] == "applied"


def test_row_domain_event_to_wire_events_solution_includes_session_fleet_torp_status(
    sample_turn,
) -> None:
    from api.analytics.military_score_inference.actions import ActionCatalog
    from api.analytics.military_score_inference.analytic import build_inference_observation
    from api.analytics.military_score_inference.inference_stream_domain_events import (
        HeldSolutionsUpdated,
    )
    from api.analytics.military_score_inference.inference_stream_rows import (
        ScheduledInferenceRow,
        row_domain_event_to_wire_events,
    )
    from api.analytics.military_score_inference.inference_stream_session import (
        InferenceRowStreamSession,
    )

    score = sample_turn.scores[0]
    observation = build_inference_observation(score, sample_turn)
    session = InferenceRowStreamSession(
        player_id=score.ownerid,
        observation=observation,
        turn=sample_turn,
        game_id=628580,
        perspective=1,
        turn_number=sample_turn.settings.turn,
        fleet_torp_input_status="pending",
    )
    solution = InferenceSolution(
        objective_value=10,
        actions=(InferenceSolutionAction(action_id="a1", label="Action A", count=1),),
    )
    event = HeldSolutionsUpdated(
        solutions=(solution,),
        catalog=ActionCatalog((), (), {}),
        observation=observation,
    )
    row = ScheduledInferenceRow(player_id=score.ownerid, session=session)
    wire_events = row_domain_event_to_wire_events(row, event)
    assert wire_events[0]["fleetTorpInputStatus"] == "pending"

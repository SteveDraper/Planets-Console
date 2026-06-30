"""Tests for scores inference NDJSON streaming."""

import json

from api.analytics.military_score_inference.models import (
    InferenceResult,
    InferenceSolution,
    InferenceSolutionAction,
)
from api.analytics.military_score_inference.row_complete_factory import row_complete_with_summary
from api.analytics.military_score_inference.solver import STATUS_EXACT
from api.transport.inference_stream import (
    inference_complete_event,
    inference_solution_event,
    stream_inference_ndjson,
)
from api.transport.inference_stream_wire import (
    domain_event_to_wire_events,
    row_complete_to_complete_wire_event,
)


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


def test_row_complete_to_complete_wire_event_includes_solutions(sample_turn) -> None:
    score = next(row for row in sample_turn.scores if row.ownerid == sample_turn.scores[0].ownerid)
    from api.analytics.military_score_inference.analytic import build_inference_observation

    observation = build_inference_observation(score, sample_turn)
    solution = InferenceSolution(
        objective_value=42,
        actions=(InferenceSolutionAction(action_id="action_a", label="Build fighter", count=2),),
    )
    wire = row_complete_to_complete_wire_event(
        row_complete_with_summary(
            InferenceResult(status=STATUS_EXACT, solutions=(solution,), diagnostics={}),
            summary="Best: built fighters",
        ),
        observation=observation,
        turn=sample_turn,
    )

    assert wire["type"] == "complete"
    assert wire["solutionCount"] == 1
    assert isinstance(wire.get("solutions"), list)
    assert len(wire["solutions"]) == 1
    assert wire["solutions"][0]["objectiveValue"] == 42
    assert wire["solutions"][0]["actions"][0]["actionId"] == "action_a"


def test_row_complete_to_complete_wire_event_promotes_fleet_torp_fields() -> None:
    from api.transport.inference_stream_wire import inference_api_payload_to_wire_complete

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
    from api.transport.inference_stream_wire import inference_api_payload_to_wire_complete

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

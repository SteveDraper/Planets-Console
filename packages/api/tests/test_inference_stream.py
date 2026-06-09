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
from api.transport.inference_stream_wire import row_complete_to_complete_wire_event


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


def test_stream_inference_ndjson_yields_error_line_on_failure() -> None:
    def failing_loader():
        raise RuntimeError("simulated defect")

    lines = list(stream_inference_ndjson(failing_loader))

    assert len(lines) == 1
    error = json.loads(lines[0])
    assert error == {"type": "error", "detail": "Internal server error"}

"""Tests for scores inference NDJSON streaming."""

import json

from api.transport.inference_stream import (
    inference_complete_event,
    inference_solution_event,
    stream_inference_ndjson,
)


def test_stream_inference_ndjson_yields_ndjson_lines() -> None:
    items = [
        inference_solution_event([{"objectiveValue": 5, "actions": []}]),
        inference_complete_event(
            status="exact",
            summary="Best: built one ship",
            solution_count=1,
            is_complete=True,
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


def test_stream_inference_ndjson_yields_error_line_on_failure() -> None:
    def failing_loader():
        raise RuntimeError("simulated defect")

    lines = list(stream_inference_ndjson(failing_loader))

    assert len(lines) == 1
    error = json.loads(lines[0])
    assert error == {"type": "error", "detail": "Internal server error"}

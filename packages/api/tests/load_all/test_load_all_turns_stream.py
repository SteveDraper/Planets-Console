"""Tests for load-all NDJSON streaming."""

import json

from api.errors import LoginCredentialsRequiredError
from api.transport.load_all_turns import (
    LoadAllProgressUpdate,
    LoadAllTurnsResponse,
    stream_load_all_turns,
)


def test_stream_load_all_turns_yields_ndjson_lines() -> None:
    items = [
        LoadAllProgressUpdate(
            phase="download",
            perspective=0,
            perspective_total=1,
            turn=0,
            turn_total=0,
            message="Downloading",
        ),
        LoadAllTurnsResponse(
            game_id=628580,
            is_game_finished=True,
            turns_written=1,
            turns_skipped=0,
            perspectives_touched=[1],
        ),
    ]

    lines = list(stream_load_all_turns(lambda: iter(items)))

    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["type"] == "progress"
    assert first["phase"] == "download"
    last = json.loads(lines[-1])
    assert last["type"] == "complete"
    assert last["result"]["game_id"] == 628580


def test_stream_load_all_turns_yields_error_line_on_planets_console_error() -> None:
    def failing_loader():
        raise LoginCredentialsRequiredError("Login credentials are required.")

    lines = list(stream_load_all_turns(failing_loader))

    assert len(lines) == 1
    error = json.loads(lines[0])
    assert error == {
        "type": "error",
        "detail": "Login credentials are required.",
        "http_error": 401,
    }


def test_stream_load_all_turns_yields_error_line_after_progress_on_unexpected_error() -> None:
    def failing_loader():
        yield LoadAllProgressUpdate(
            phase="import",
            perspective=1,
            perspective_total=1,
            turn=1,
            turn_total=1,
            message="Turn 1",
        )
        raise RuntimeError("simulated defect")

    lines = list(stream_load_all_turns(failing_loader))

    assert len(lines) == 2
    progress = json.loads(lines[0])
    assert progress["type"] == "progress"
    error = json.loads(lines[1])
    assert error == {"type": "error", "detail": "Internal server error", "http_error": 500}

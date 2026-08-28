"""BFF inference cell displayStatus mapping for skip, residual, and failure."""

import json
from unittest.mock import MagicMock, patch

from bff.analytics.scores import (
    INFERENCE_SKIP_DISPLAY_STATUSES,
    inference_from_core,
    stamp_inference_stream_display_status,
)
from bff.app import app
from fastapi.testclient import TestClient


def _core_row(
    *,
    status: str,
    summary: str = "row",
    solution_count: int = 0,
    is_complete: bool = True,
    solutions: list | None = None,
    unexplained_military_delta_2x: int | None = None,
    placeholders: list | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "summary": summary,
        "solutionCount": solution_count,
        "isComplete": is_complete,
        "solutions": solutions if solutions is not None else [],
        "diagnostics": {},
    }
    if unexplained_military_delta_2x is not None:
        payload["unexplainedMilitaryDelta2x"] = unexplained_military_delta_2x
    if placeholders is not None:
        payload["placeholders"] = placeholders
    return payload


def test_skip_statuses_map_to_skipped_display_status() -> None:
    assert INFERENCE_SKIP_DISPLAY_STATUSES == {
        "viewpoint_owner",
        "dead",
        "full_alliance",
        "horwasp",
        "no_prior_turn",
        "player_not_found",
    }
    for status in sorted(INFERENCE_SKIP_DISPLAY_STATUSES):
        shaped = inference_from_core(_core_row(status=status, summary="skipped row"), player_id=2)
        assert shaped["displayStatus"] == "skipped"
        assert shaped["status"] == status
        assert shaped["solutionCount"] == 0


def test_unknown_complete_status_is_failure_not_skipped() -> None:
    shaped = inference_from_core(
        _core_row(status="novel_terminal", summary="unrecognized complete"),
        player_id=2,
    )
    assert shaped["displayStatus"] == "failure"
    assert shaped["status"] == "novel_terminal"


def test_empty_complete_status_is_failure_not_skipped() -> None:
    shaped = inference_from_core(_core_row(status=""), player_id=2)
    assert shaped["displayStatus"] == "failure"


def test_residual_statuses_map_to_matching_display_status() -> None:
    moderate = inference_from_core(
        _core_row(
            status="moderate_residual",
            unexplained_military_delta_2x=22,
            placeholders=[],
        ),
        player_id=3,
    )
    mine = inference_from_core(
        _core_row(
            status="mine_score_residual",
            unexplained_military_delta_2x=54,
            placeholders=[],
        ),
        player_id=4,
    )
    assert moderate["displayStatus"] == "moderate_residual"
    assert moderate["unexplainedMilitaryDelta2x"] == 22
    assert moderate["placeholders"] == []
    assert mine["displayStatus"] == "mine_score_residual"
    assert mine["unexplainedMilitaryDelta2x"] == 54


def test_failure_statuses_stay_failure() -> None:
    for status in ("no_exact_solution", "invalid_problem", "solver_error", "fetch_error"):
        shaped = inference_from_core(_core_row(status=status), player_id=5)
        assert shaped["displayStatus"] == "failure"
        assert shaped["status"] == status


def test_time_limited_complete_maps_held_to_success_and_zero_to_failure() -> None:
    held = inference_from_core(
        _core_row(
            status="time_limited",
            solution_count=2,
            solutions=[{"objectiveValue": 1}, {"objectiveValue": 2}],
        ),
        player_id=8,
    )
    zero = inference_from_core(_core_row(status="time_limited"), player_id=9)
    in_flight = inference_from_core(
        _core_row(status="time_limited", is_complete=False),
        player_id=10,
    )
    assert held["displayStatus"] == "success"
    assert zero["displayStatus"] == "failure"
    assert in_flight["displayStatus"] == "pending"


def test_unavailable_build_inference_ignores_include_flag() -> None:
    from bff.analytics.scores import table_from_core

    payload = table_from_core(
        {"rows": [], "buildInferenceAvailable": False},
        include_build_inference=True,
    )
    assert payload["buildInferenceAvailable"] is False
    assert "includeBuildInference" not in payload
    assert "inferenceByRow" not in payload
    assert "Build inference" not in payload["columns"]


def test_exact_and_in_flight_held_solutions_stay_success() -> None:
    exact = inference_from_core(
        _core_row(status="exact", solution_count=1, solutions=[{"objectiveValue": 1}]),
        player_id=6,
    )
    in_flight = inference_from_core(
        _core_row(
            status="pending",
            solution_count=1,
            is_complete=False,
            solutions=[{"objectiveValue": 1}],
        ),
        player_id=7,
    )
    assert exact["displayStatus"] == "success"
    assert in_flight["displayStatus"] == "success"


def test_stamp_inference_stream_display_status_on_complete_only() -> None:
    events = list(
        stamp_inference_stream_display_status(
            iter(
                [
                    {"type": "progress", "policyStepId": "tier_1"},
                    {
                        "type": "complete",
                        "status": "dead",
                        "summary": "Player is dead",
                        "solutionCount": 0,
                        "isComplete": True,
                    },
                    {
                        "type": "complete",
                        "status": "novel_terminal",
                        "summary": "unknown",
                        "solutionCount": 0,
                        "isComplete": True,
                    },
                ]
            )
        )
    )
    assert events[0] == {"type": "progress", "policyStepId": "tier_1"}
    assert events[1]["displayStatus"] == "skipped"
    assert events[1]["status"] == "dead"
    assert events[2]["displayStatus"] == "failure"
    assert events[2]["status"] == "novel_terminal"


def test_scores_inference_table_stream_stamps_display_status() -> None:
    def _iter_scores_table_inference_stream(
        game_id: int,
        perspective: int,
        turn_number: int,
        player_ids: tuple[int, ...],
        *,
        username: str = "",
    ):
        del game_id, perspective, turn_number, player_ids, username
        yield {
            "type": "complete",
            "playerId": 3,
            "status": "dead",
            "summary": "Player is dead",
            "solutionCount": 0,
            "isComplete": True,
        }
        yield {
            "type": "complete",
            "playerId": 4,
            "status": "novel_terminal",
            "summary": "unrecognized complete",
            "solutionCount": 0,
            "isComplete": True,
        }

    mock_core = MagicMock()
    mock_core.iter_scores_table_inference_stream = _iter_scores_table_inference_stream
    client = TestClient(app)
    with patch("bff.routers.scores_inference.get_core_client", return_value=mock_core):
        response = client.get(
            "/analytics/scores/inference/table-stream"
            "?gameId=628580&perspective=1&turn=8&playerIds=3,4"
        )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert events[0]["displayStatus"] == "skipped"
    assert events[0]["status"] == "dead"
    assert events[1]["displayStatus"] == "failure"
    assert events[1]["status"] == "novel_terminal"

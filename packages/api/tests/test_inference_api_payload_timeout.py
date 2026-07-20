"""Inference API payload terminal flags for timeout outcomes."""

from __future__ import annotations

from api.analytics.military_score_inference.inference_api_payload import inference_api_payload
from api.analytics.military_score_inference.models import (
    InferenceSolution,
    InferenceSolutionAction,
)
from api.analytics.military_score_inference.solver import STATUS_TIME_LIMITED


def test_zero_solution_time_limited_payload_is_complete_terminal_error() -> None:
    payload = inference_api_payload(
        status=STATUS_TIME_LIMITED,
        summary="Inference timed out before finding a solution",
        solutions=(),
        diagnostics={},
    )
    assert payload["isComplete"] is True
    assert payload["status"] == STATUS_TIME_LIMITED
    assert payload["solutionCount"] == 0


def test_partial_time_limited_payload_stays_incomplete_for_streaming() -> None:
    payload = inference_api_payload(
        status=STATUS_TIME_LIMITED,
        summary="Timed out with held solutions",
        solutions=(
            InferenceSolution(
                objective_value=10,
                actions=(
                    InferenceSolutionAction(
                        action_id="planet_defense_posts_added_total",
                        label="Planet defense",
                        count=1,
                    ),
                ),
                ship_builds=(),
            ),
        ),
        diagnostics={},
    )
    assert payload["isComplete"] is False
    assert payload["solutionCount"] == 1

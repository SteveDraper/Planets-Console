"""NDJSON wire events and line encoding for military score build inference streams."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from typing import TypeAlias

from api.errors import PlanetsConsoleError

logger = logging.getLogger(__name__)

_INFERENCE_STREAM_UNEXPECTED_ERROR_DETAIL = "Internal server error"

TABLE_STREAM_ALREADY_ACTIVE_DETAIL = "An inference table stream is already active for this scope."


def inference_solution_event(
    solutions: list[dict[str, object]],
    *,
    segment_id: str | None = None,
    scoreboard_delta_source: str | None = None,
) -> dict[str, object]:
    """Emit the full held top-K for one row after a new signature is admitted."""
    payload: dict[str, object] = {"type": "solution", "solutions": solutions}
    if segment_id is not None:
        payload["segmentId"] = segment_id
    if scoreboard_delta_source is not None:
        payload["scoreboardDeltaSource"] = scoreboard_delta_source
    return payload


def inference_progress_event(
    *,
    policy_step_id: str | None = None,
    combo_count: int | None = None,
    held_count: int | None = None,
    solver_status: str | None = None,
    elapsed_seconds: float | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"type": "progress"}
    if policy_step_id is not None:
        payload["policyStepId"] = policy_step_id
    if combo_count is not None:
        payload["comboCount"] = combo_count
    if held_count is not None:
        payload["heldCount"] = held_count
    if solver_status is not None:
        payload["solverStatus"] = solver_status
    if elapsed_seconds is not None:
        payload["elapsedSeconds"] = elapsed_seconds
    return payload


def inference_complete_event(
    *,
    status: str,
    summary: str,
    solution_count: int,
    is_complete: bool = True,
    diagnostics: dict[str, object] | None = None,
    solutions: list[dict[str, object]] | None = None,
    host_turn_targets: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "complete",
        "status": status,
        "summary": summary,
        "solutionCount": solution_count,
        "isComplete": is_complete,
    }
    if solutions is not None:
        payload["solutions"] = solutions
    if diagnostics is not None:
        payload["diagnostics"] = diagnostics
    if host_turn_targets is not None:
        payload["hostTurnTargets"] = host_turn_targets
    return payload


def inference_error_event(detail: str) -> dict[str, object]:
    return {"type": "error", "detail": detail}


def inference_global_pause_event(*, paused: bool) -> dict[str, object]:
    return {"type": "globalPause", "paused": paused}


InferenceStreamItem: TypeAlias = dict[str, object]


def iter_inference_ndjson_lines(iterator: Iterator[InferenceStreamItem]) -> Iterator[str]:
    for item in iterator:
        yield json.dumps(item) + "\n"


def _inference_stream_error_detail(exc: BaseException) -> str:
    if isinstance(exc, PlanetsConsoleError):
        return str(exc) or _INFERENCE_STREAM_UNEXPECTED_ERROR_DETAIL
    return _INFERENCE_STREAM_UNEXPECTED_ERROR_DETAIL


def stream_inference_ndjson(
    stream_iterator: Callable[[], Iterator[InferenceStreamItem]],
) -> Iterator[str]:
    """Run an inference event iterator and yield NDJSON lines."""
    try:
        yield from iter_inference_ndjson_lines(stream_iterator())
    except Exception as exc:
        if not isinstance(exc, PlanetsConsoleError):
            logger.exception("Inference NDJSON stream failed")
        yield json.dumps(inference_error_event(_inference_stream_error_detail(exc))) + "\n"

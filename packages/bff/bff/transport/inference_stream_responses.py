"""BFF OpenAPI models for scores inference NDJSON stream events."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class InferenceStreamSolutionEvent(BaseModel):
    type: Literal["solution"]
    solutions: list[dict[str, Any]]
    segmentId: str | None = None
    scoreboardDeltaSource: str | None = None


class InferenceStreamProgressEvent(BaseModel):
    type: Literal["progress"]
    policyStepId: str | None = None
    comboCount: int | None = None
    heldCount: int | None = None
    solverStatus: str | None = None
    elapsedSeconds: float | None = None


class InferenceStreamCompleteEvent(BaseModel):
    type: Literal["complete"]
    status: str
    summary: str
    solutionCount: int
    isComplete: bool = True
    solutions: list[dict[str, Any]] | None = None
    diagnostics: dict[str, Any] | None = None
    fleetTorpInputStatus: str | None = None
    fleetTorpOverlayBeliefSetTorpIds: list[int] | None = None


class InferenceStreamErrorEvent(BaseModel):
    type: Literal["error"]
    detail: str


__all__ = [
    "InferenceStreamCompleteEvent",
    "InferenceStreamErrorEvent",
    "InferenceStreamProgressEvent",
    "InferenceStreamSolutionEvent",
]
